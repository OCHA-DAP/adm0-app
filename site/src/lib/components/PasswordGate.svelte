<script lang="ts">
  import { onMount } from "svelte";
  import { unlock } from "$lib/unlock";

  let { onunlock }: { onunlock: (tilesBase: string) => void } = $props();

  const STORAGE_KEY = "adm0-site-password";
  const URL_PARAM = "pw";

  let password = $state("");
  let error = $state(false);

  async function tryUnlock(value: string, remember: boolean) {
    const url = await unlock(value);
    if (url) {
      if (remember) sessionStorage.setItem(STORAGE_KEY, value);
      onunlock(url);
    }
    return url !== null;
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = !(await tryUnlock(password, true));
  }

  onMount(() => {
    const url = new URL(location.href);
    const shared = url.searchParams.get(URL_PARAM);
    if (shared !== null) {
      url.searchParams.delete(URL_PARAM);
      history.replaceState(null, "", url);
    }
    const saved = shared ?? sessionStorage.getItem(STORAGE_KEY);
    if (saved) tryUnlock(saved, shared !== null);
  });
</script>

<form onsubmit={submit}>
  <label>
    Password
    <!-- svelte-ignore a11y_autofocus -->
    <input type="password" bind:value={password} autofocus />
  </label>
  <button type="submit">Open</button>
  {#if error}<p>Incorrect password.</p>{/if}
</form>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    width: 18rem;
    margin: 20vh auto;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  input,
  button {
    padding: 0.5rem 0.75rem;
    font-size: 1rem;
    border-radius: var(--brand-radius--sm);
  }
  button {
    background: var(--brand-primary--text);
    color: var(--cd-white);
    border: 0;
    font-weight: 500;
    cursor: pointer;
  }
  button:hover {
    background: var(--brand-primary--dark);
  }
  p {
    color: var(--cd-red--aa);
    margin: 0;
  }
</style>
