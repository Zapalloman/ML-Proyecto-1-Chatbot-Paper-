<script lang="ts">
	import { MODELS, chat, type Model } from '$lib/chat.svelte';

	let { disabled = false }: { disabled?: boolean } = $props();

	function onChange(e: Event) {
		const value = (e.currentTarget as HTMLSelectElement).value as Model;
		chat.setModel(value);
	}
</script>

<label class="model-selector">
	<span class="label">Modelo</span>
	<select value={chat.model} onchange={onChange} {disabled}>
		{#each MODELS as m (m)}
			<option value={m}>{m}</option>
		{/each}
	</select>
</label>
