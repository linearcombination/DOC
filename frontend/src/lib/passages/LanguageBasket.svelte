<script lang="ts">
  import { goto } from '$app/navigation'
  import { page } from '$app/stores'
  import {
    langCodesStore,
    langCountStore,
    languagesClickedOrderStore
  } from '$lib/passages/stores/LanguagesStore'
  import { clearPassages } from '$lib/passages/stores/PassagesStore'
  import { langRegExp, getCode, getName } from '$lib/passages/utils'
  import CloseIcon from '$lib/CloseIcon.svelte'
  import EditIcon from '$lib/EditIcon.svelte'
  import GlobeIcon from '$lib/GlobeIcon.svelte'

  function uncheckLanguage(langCodeAndName: string) {
    $languagesClickedOrderStore = $languagesClickedOrderStore.filter(
      (item) => item != langCodeAndName
    )
    $langCodesStore = $langCodesStore.filter((item) => item != getCode(langCodeAndName))
    $langCountStore = $langCodesStore.length
    // passages chosen no longer correspond to the chosen languages
    clearPassages()
  }
</script>

{#if langRegExp.test($page.url.pathname)}
  <div class="my-2 flex items-center">
    <GlobeIcon />
    <h2 class="ml-2 text-xl font-semibold text-[#33445C]">Language</h2>
  </div>
{:else}
  <div class="my-2 flex items-center justify-between">
    <div class="flex items-center justify-between">
      <GlobeIcon />
      <h2 class="ml-2 text-xl font-semibold text-[#33445C]">Language</h2>
    </div>
    <button
      class="flex rounded bg-white px-4 py-2 text-xl text-[#33445c] hover:bg-[#efefef]"
      on:click={() => goto('/passages/language')}
    >
      <EditIcon />
      <span class="ml-2"> Edit </span>
    </button>
  </div>
{/if}

{#if $languagesClickedOrderStore && $languagesClickedOrderStore.length > 0}
  {#each $languagesClickedOrderStore as langCodeAndName}
    {#if langRegExp.test($page.url.pathname)}
      <div
        class="mt-2 flex w-full items-center justify-between
                 rounded-lg bg-white p-4 text-xl text-[#66768B]"
      >
        <div>
          <span>{getName(langCodeAndName)}</span><span class="ml-2"
            >({getCode(langCodeAndName)})</span
          >
        </div>
        <button on:click={() => uncheckLanguage(langCodeAndName)}>
          <CloseIcon />
        </button>
      </div>
    {:else}
      <div
        class="mt-2 flex w-full items-center justify-between
                 rounded-lg bg-white p-4 text-xl text-[#66768B]"
      >
        <div>
          <span>{getName(langCodeAndName)}</span><span class="ml-2"
            >({getCode(langCodeAndName)})</span
          >
        </div>
      </div>
    {/if}
  {/each}
{:else}
  <div class="rounded-lg bg-[#e5e8eb] p-6 text-xl text-[#66768b]">
    Selections will appear here once a language is selected
  </div>
{/if}
