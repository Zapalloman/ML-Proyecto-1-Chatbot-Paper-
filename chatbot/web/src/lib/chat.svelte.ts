/**
 * Chat state for the Pokédex chatbot UI.
 *
 * Holds the conversation, the currently-selected model, and the in-flight
 * streaming state. Persists messages + model selection in sessionStorage so a
 * page reload preserves the active chat (per-tab, as the assignment expects).
 */

import { browser } from '$app/environment';

export const MODELS = ['gemma3:4b', 'qwen2.5:3b'] as const;
export type Model = (typeof MODELS)[number];
export const DEFAULT_MODEL: Model = 'gemma3:4b';

export type Role = 'user' | 'assistant' | 'system';
export type RetrievedDoc = { id: number; name: string; score: number };

export type ChatMessage = {
	role: Role;
	content: string;
	/** Model that produced this assistant turn. */
	model?: Model;
	/** Detected language for the user turn this answered (es/en). */
	lang?: string;
	/** Top-k species cited for this answer. */
	retrieved?: RetrievedDoc[];
	/** Set when the request failed; UI shows error state with a retry. */
	error?: string;
	/** True while tokens are still streaming. */
	streaming?: boolean;
};

const STORAGE_KEY = 'pokedex-chat-v1';

type Persisted = { messages: ChatMessage[]; model: Model };

function loadPersisted(): Persisted | null {
	if (!browser) return null;
	try {
		const raw = sessionStorage.getItem(STORAGE_KEY);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as Persisted;
		if (!Array.isArray(parsed.messages)) return null;
		const model = (MODELS as readonly string[]).includes(parsed.model)
			? (parsed.model as Model)
			: DEFAULT_MODEL;
		return { messages: parsed.messages, model };
	} catch {
		return null;
	}
}

class ChatState {
	messages = $state<ChatMessage[]>([]);
	model = $state<Model>(DEFAULT_MODEL);
	sending = $state(false);

	#abort: AbortController | null = null;

	constructor() {
		const initial = loadPersisted();
		if (initial) {
			this.messages = initial.messages.map((m) => ({ ...m, streaming: false }));
			this.model = initial.model;
		}
	}

	persist() {
		if (!browser) return;
		try {
			const payload: Persisted = { messages: this.messages, model: this.model };
			sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
		} catch {
			// quota exceeded or storage disabled — silently drop persistence
		}
	}

	setModel(m: Model) {
		this.model = m;
		this.persist();
	}

	clear() {
		this.cancel();
		this.messages = [];
		this.persist();
	}

	cancel() {
		this.#abort?.abort();
		this.#abort = null;
		const last = this.messages[this.messages.length - 1];
		if (last && last.streaming) {
			last.streaming = false;
		}
		this.sending = false;
	}

	/** Drop a failed assistant turn and re-send the prior user message. */
	async retryLast() {
		const last = this.messages[this.messages.length - 1];
		if (!last || last.role !== 'assistant' || !last.error) return;
		this.messages = this.messages.slice(0, -1);
		const prevUser = this.messages[this.messages.length - 1];
		if (!prevUser || prevUser.role !== 'user') return;
		await this.#stream();
	}

	async send(text: string) {
		const trimmed = text.trim();
		if (!trimmed || this.sending) return;
		this.messages.push({ role: 'user', content: trimmed });
		await this.#stream();
	}

	async #stream() {
		const model = this.model;
		const history = this.messages
			.filter((m) => !m.error)
			.map((m) => ({ role: m.role, content: m.content }));

		const placeholder: ChatMessage = {
			role: 'assistant',
			content: '',
			model,
			streaming: true
		};
		this.messages.push(placeholder);
		this.sending = true;
		this.persist();

		const ac = new AbortController();
		this.#abort = ac;

		try {
			const resp = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ messages: history, model }),
				signal: ac.signal
			});

			if (!resp.ok || !resp.body) {
				const detail = await resp.text().catch(() => '');
				throw new Error(detail || `HTTP ${resp.status}`);
			}

			const reader = resp.body.getReader();
			const decoder = new TextDecoder();
			let buf = '';
			let currentEvent = 'message';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += decoder.decode(value, { stream: true });
				const parts = buf.split('\n\n');
				buf = parts.pop() ?? '';
				for (const block of parts) {
					const lines = block.split('\n');
					let event = 'message';
					let data = '';
					for (const line of lines) {
						if (line.startsWith('event:')) event = line.slice(6).trim();
						else if (line.startsWith('data:')) data += line.slice(5).trim();
					}
					currentEvent = event;
					if (!data) continue;
					this.#handleEvent(currentEvent, data);
				}
			}
		} catch (err) {
			const aborted = (err as Error)?.name === 'AbortError';
			const last = this.messages[this.messages.length - 1];
			if (last && last.role === 'assistant') {
				last.streaming = false;
				if (aborted) {
					if (!last.content) {
						this.messages = this.messages.slice(0, -1);
					}
				} else {
					last.error = (err as Error).message || 'Request failed';
				}
			}
		} finally {
			const last = this.messages[this.messages.length - 1];
			if (last && last.role === 'assistant') last.streaming = false;
			this.sending = false;
			this.#abort = null;
			this.persist();
		}
	}

	#handleEvent(event: string, dataRaw: string) {
		const last = this.messages[this.messages.length - 1];
		if (!last || last.role !== 'assistant') return;
		let data: unknown;
		try {
			data = JSON.parse(dataRaw);
		} catch {
			return;
		}
		if (event === 'meta' && data && typeof data === 'object') {
			const d = data as { model?: Model; lang?: string; retrieved?: RetrievedDoc[] };
			if (d.model) last.model = d.model;
			if (d.lang) last.lang = d.lang;
			if (Array.isArray(d.retrieved)) last.retrieved = d.retrieved;
		} else if (event === 'token' && data && typeof data === 'object') {
			const d = data as { text?: string };
			if (typeof d.text === 'string') last.content += d.text;
		} else if (event === 'error' && data && typeof data === 'object') {
			const d = data as { message?: string; status?: number };
			last.error = d.message || `error ${d.status ?? ''}`.trim();
		}
	}
}

export const chat = new ChatState();
