/**
 * POST /api/chat
 *
 * Streams a Pokédex-grounded chat response.
 *
 * Request body:
 *   {
 *     messages: [{ role: 'user' | 'assistant' | 'system', content: string }, ...],
 *     model?:   'gemma3:4b' | 'qwen2.5:3b' | 'gemma3:1b',
 *     k?:       number  // top-k retrieval, default 5
 *   }
 *
 * Behavior:
 *   1. Resolve effective model: body.model -> env OLLAMA_MODEL -> default 'gemma3:4b'.
 *      Validate against allowlist; reject unknown models with 400.
 *   2. Forward the chat history to the Python RAG bridge (`POST /build_prompt`),
 *      which performs hybrid retrieval and assembles the system+context prompt.
 *   3. Forward the assembled messages to Ollama's OpenAI-compatible streaming
 *      endpoint and pipe SSE chunks straight to the client.
 *
 * Response: text/event-stream with two custom event names plus the
 * Ollama deltas:
 *   event: meta            (single meta line — model + retrieved doc names)
 *   event: token           (one per generated token chunk)
 *   event: done            (terminal)
 *   event: error           (on failure)
 */

import type { RequestHandler } from './$types';
import { error } from '@sveltejs/kit';

const ALLOWED_MODELS = ['gemma3:4b', 'qwen2.5:3b', 'gemma3:1b'] as const;
type AllowedModel = (typeof ALLOWED_MODELS)[number];
const DEFAULT_MODEL: AllowedModel = 'gemma3:4b';

const RAG_API = process.env.RAG_API_URL ?? 'http://127.0.0.1:8001';
const OLLAMA_URL = process.env.OLLAMA_URL ?? 'http://127.0.0.1:11434';
const OLLAMA_TIMEOUT_MS = 120_000;

type ChatMessage = { role: 'user' | 'assistant' | 'system'; content: string };

function resolveModel(requested: unknown): AllowedModel {
	const fromBody = typeof requested === 'string' ? requested : null;
	const fromEnv = process.env.OLLAMA_MODEL ?? null;
	const candidate = fromBody ?? fromEnv ?? DEFAULT_MODEL;
	if (!(ALLOWED_MODELS as readonly string[]).includes(candidate)) {
		throw error(400, `model must be one of: ${ALLOWED_MODELS.join(', ')}`);
	}
	return candidate as AllowedModel;
}

function sse(event: string, data: unknown): string {
	const payload = typeof data === 'string' ? data : JSON.stringify(data);
	return `event: ${event}\ndata: ${payload}\n\n`;
}

export const POST: RequestHandler = async ({ request }) => {
	let body: { messages?: ChatMessage[]; model?: string; k?: number };
	try {
		body = await request.json();
	} catch {
		throw error(400, 'request body must be JSON');
	}
	const messages = body.messages ?? [];
	if (
		!Array.isArray(messages) ||
		messages.length === 0 ||
		messages[messages.length - 1].role !== 'user' ||
		typeof messages[messages.length - 1].content !== 'string'
	) {
		throw error(400, 'messages must be a non-empty array ending with a user message');
	}
	const model = resolveModel(body.model);
	const k = typeof body.k === 'number' && body.k > 0 ? Math.min(body.k, 10) : 5;

	// 1. Build prompt via RAG bridge (retrieval + system+context assembly).
	let promptResp: Response;
	try {
		promptResp = await fetch(`${RAG_API}/build_prompt`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ messages, k })
		});
	} catch (err) {
		throw error(502, `RAG bridge unreachable: ${(err as Error).message}`);
	}
	if (!promptResp.ok) {
		const detail = await promptResp.text();
		throw error(502, `RAG bridge error ${promptResp.status}: ${detail}`);
	}
	const prompt = (await promptResp.json()) as {
		messages: ChatMessage[];
		retrieved: { species_id: number; name: string; score: number }[];
		lang: string;
	};

	// 2. Stream from Ollama OpenAI-compat endpoint, transcode to SSE.
	const stream = new ReadableStream<Uint8Array>({
		async start(controller) {
			const enc = new TextEncoder();
			const meta = {
				model,
				lang: prompt.lang,
				retrieved: prompt.retrieved.map((d) => ({
					id: d.species_id,
					name: d.name,
					score: Number(d.score.toFixed(4))
				}))
			};
			controller.enqueue(enc.encode(sse('meta', meta)));

			const ac = new AbortController();
			const timer = setTimeout(() => ac.abort(), OLLAMA_TIMEOUT_MS);
			let upstream: Response;
			try {
				upstream = await fetch(`${OLLAMA_URL}/v1/chat/completions`, {
					method: 'POST',
					signal: ac.signal,
					headers: { 'content-type': 'application/json' },
					body: JSON.stringify({
						model,
						messages: prompt.messages,
						stream: true,
						temperature: 0.4
					})
				});
			} catch (err) {
				clearTimeout(timer);
				controller.enqueue(enc.encode(sse('error', { message: (err as Error).message })));
				controller.close();
				return;
			}

			if (!upstream.ok || !upstream.body) {
				clearTimeout(timer);
				const detail = await upstream.text();
				controller.enqueue(
					enc.encode(sse('error', { status: upstream.status, message: detail }))
				);
				controller.close();
				return;
			}

			const reader = upstream.body.getReader();
			const decoder = new TextDecoder();
			let buf = '';
			try {
				while (true) {
					const { done, value } = await reader.read();
					if (done) break;
					buf += decoder.decode(value, { stream: true });
					const lines = buf.split('\n');
					buf = lines.pop() ?? '';
					for (const line of lines) {
						const t = line.trim();
						if (!t.startsWith('data:')) continue;
						const data = t.slice(5).trim();
						if (!data || data === '[DONE]') continue;
						try {
							const json = JSON.parse(data);
							const delta = json.choices?.[0]?.delta?.content;
							if (typeof delta === 'string' && delta.length > 0) {
								controller.enqueue(enc.encode(sse('token', { text: delta })));
							}
						} catch {
							// ignore unparseable chunks (Ollama occasionally emits keepalives)
						}
					}
				}
			} finally {
				clearTimeout(timer);
				controller.enqueue(enc.encode(sse('done', { ok: true })));
				controller.close();
			}
		}
	});

	return new Response(stream, {
		headers: {
			'content-type': 'text/event-stream; charset=utf-8',
			'cache-control': 'no-cache, no-transform',
			'x-accel-buffering': 'no'
		}
	});
};
