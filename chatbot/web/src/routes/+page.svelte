<script lang="ts">
	import { tick } from 'svelte';
	import { chat } from '$lib/chat.svelte';
	import Message from '$lib/components/Message.svelte';
	import ModelSelector from '$lib/components/ModelSelector.svelte';

	let input = $state('');
	let listEl: HTMLDivElement | undefined = $state();
	let textareaEl: HTMLTextAreaElement | undefined = $state();

	const lastAssistantHasError = $derived.by(() => {
		const last = chat.messages[chat.messages.length - 1];
		return !!(last && last.role === 'assistant' && last.error);
	});

	async function scrollToBottom() {
		await tick();
		if (!listEl) return;
		listEl.scrollTop = listEl.scrollHeight;
	}

	$effect(() => {
		void chat.messages.length;
		const last = chat.messages[chat.messages.length - 1];
		void last?.content?.length;
		scrollToBottom();
	});

	async function submit(e?: Event) {
		e?.preventDefault();
		const text = input.trim();
		if (!text || chat.sending) return;
		input = '';
		if (textareaEl) textareaEl.style.height = 'auto';
		await chat.send(text);
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit();
		}
	}

	function autosize(e: Event) {
		const ta = e.currentTarget as HTMLTextAreaElement;
		ta.style.height = 'auto';
		ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
	}

	function clearConversation() {
		if (chat.messages.length === 0) return;
		if (!confirm('¿Borrar la conversación?')) return;
		chat.clear();
	}
</script>

<svelte:head>
	<title>Pokédex Chatbot</title>
</svelte:head>

<div class="app">
	<header class="topbar">
		<div class="brand">
			<span class="dot"></span>
			<h1>Pokédex Chatbot</h1>
		</div>
		<div class="controls">
			<ModelSelector disabled={chat.sending} />
			<button
				type="button"
				class="ghost"
				onclick={clearConversation}
				disabled={chat.sending || chat.messages.length === 0}
				title="Borrar conversación"
			>
				Limpiar
			</button>
		</div>
	</header>

	<div class="messages" bind:this={listEl}>
		{#if chat.messages.length === 0}
			<div class="empty">
				<h2>Pregúntame sobre Pokémon</h2>
				<p>Ask me anything about Pokémon — types, stats, evolutions, lore.</p>
				<ul class="suggestions">
					<li>¿Qué tipo es Garchomp?</li>
					<li>Compare base stats of Mewtwo and Mew.</li>
					<li>¿Cuál es la cadena evolutiva de Eevee?</li>
				</ul>
			</div>
		{:else}
			{#each chat.messages as msg, i (i)}
				<Message
					message={msg}
					onRetry={i === chat.messages.length - 1 && lastAssistantHasError
						? () => chat.retryLast()
						: undefined}
				/>
			{/each}
		{/if}
	</div>

	<form class="composer" onsubmit={submit}>
		<textarea
			bind:this={textareaEl}
			bind:value={input}
			oninput={autosize}
			onkeydown={onKeydown}
			placeholder="Pregunta algo sobre Pokémon..."
			rows="1"
			disabled={chat.sending}
		></textarea>
		<button type="submit" class="send" disabled={chat.sending || input.trim().length === 0}>
			{chat.sending ? '…' : 'Enviar'}
		</button>
	</form>
</div>
