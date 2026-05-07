<script lang="ts">
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';
	import type { ChatMessage } from '$lib/chat.svelte';

	let { message, onRetry }: { message: ChatMessage; onRetry?: () => void } = $props();

	marked.setOptions({ breaks: true, gfm: true });

	const html = $derived.by(() => {
		if (!message.content) return '';
		const raw = marked.parse(message.content, { async: false }) as string;
		return DOMPurify.sanitize(raw, {
			ALLOWED_TAGS: [
				'p', 'br', 'strong', 'em', 'code', 'pre',
				'ul', 'ol', 'li', 'blockquote', 'a', 'h1', 'h2', 'h3', 'h4', 'hr'
			],
			ALLOWED_ATTR: ['href', 'title']
		});
	});
</script>

<article class="msg msg-{message.role}" class:streaming={message.streaming} class:errored={!!message.error}>
	<header class="meta">
		<span class="role">{message.role === 'user' ? 'Tú' : 'Pokédex'}</span>
		{#if message.role === 'assistant' && message.model}
			<span class="badge model" title="Modelo que respondió">{message.model}</span>
		{/if}
		{#if message.role === 'assistant' && message.lang}
			<span class="badge lang" title="Idioma detectado">{message.lang}</span>
		{/if}
	</header>

	{#if message.error}
		<p class="error">⚠ {message.error}</p>
		{#if onRetry}
			<button type="button" class="retry" onclick={onRetry}>Reintentar</button>
		{/if}
	{:else if message.role === 'assistant'}
		<div class="body">
			{#if html}
				<!-- eslint-disable-next-line svelte/no-at-html-tags -->
				{@html html}
			{:else if message.streaming}
				<span class="cursor">▍</span>
			{/if}
			{#if message.streaming && html}
				<span class="cursor">▍</span>
			{/if}
		</div>
	{:else}
		<div class="body user-text">{message.content}</div>
	{/if}

	{#if message.role === 'assistant' && message.retrieved && message.retrieved.length > 0}
		<footer class="cited">
			<span class="cited-label">Citado:</span>
			{#each message.retrieved as r (r.id)}
				<span class="chip" title="score {r.score}">{r.name}</span>
			{/each}
		</footer>
	{/if}
</article>
