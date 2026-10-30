<script lang="ts">
  import MobileLanguageDisplay from './MobileLanguageDisplay.svelte'
  import DesktopLanguageDisplay from './DesktopLanguageDisplay.svelte'

  import Languages from '$lib/Languages.svelte'
  import WizardBreadcrumb from '$lib/passages/WizardBreadcrumb.svelte'
  import WizardBasket from '$lib/passages/WizardBasket.svelte'
  import { clearPassages } from '$lib/passages/stores/PassagesStore'

  import {
    langCodesStore,
    langCountStore,
    langNamesStore,
    languagesClickedOrderStore
  } from '$lib/passages/stores/LanguagesStore'

  function handleLangChange(e: Event, lang: string) {
    const input = e.currentTarget as HTMLInputElement
    languagesClickedOrderStore.update((arr) => {
      if (input.checked) {
        // append only if not already present
        return arr.includes(lang) ? arr : [...arr, lang]
      } else {
        // remove if unchecked
        return arr.filter((v) => v !== lang)
      }
    })
    // passages chosen no longer correspond to the chosen languages
    clearPassages()
  }
</script>

<Languages
  message="Select up to 2 languages"
  {handleLangChange}
  {WizardBreadcrumb}
  {WizardBasket}
  {MobileLanguageDisplay}
  {DesktopLanguageDisplay}
  {languagesClickedOrderStore}
  {langCodesStore}
  {langNamesStore}
  {langCountStore}
/>
