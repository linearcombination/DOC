import { writable } from 'svelte/store'
import type { BibleReference } from '../models'

// Define the passages store
export const passagesStore = writable<BibleReference[]>([])
export const availablePassagesStore = writable<BibleReference[]>([])

// Passages chosen no longer correspond once the chosen languages change
export function clearPassages() {
  passagesStore.set([])
  availablePassagesStore.set([])
}

export function addBibleReference(ref: BibleReference) {
  passagesStore.update((currentPassages) => {
    // Check if the passage already exists
    const exists = currentPassages.some(
      (p) =>
        p.langCode === ref.langCode &&
        p.bookCode === ref.bookCode &&
        p.startChapter === ref.startChapter &&
        p.startChapterVerseRef === ref.startChapterVerseRef &&
        p.endChapter === ref.endChapter &&
        p.endChapterVerseRef === ref.endChapterVerseRef
    )
    if (exists) {
      return currentPassages // Return unchanged if passage exists
    }
    return [...currentPassages, ref]
  })
}

export function addAvailableBibleReference(ref: BibleReference) {
  availablePassagesStore.update((currentPassages) => {
    // Check if the passage already exists
    const exists = currentPassages.some(
      (p) =>
        p.langCode === ref.langCode &&
        p.bookCode === ref.bookCode &&
        p.startChapter === ref.startChapter &&
        p.startChapterVerseRef === ref.startChapterVerseRef &&
        p.endChapter === ref.endChapter &&
        p.endChapterVerseRef === ref.endChapterVerseRef
    )
    if (exists) {
      return currentPassages // Return unchanged if passage exists
    }
    return [...currentPassages, ref]
  })
}

export function removeBibleReference(ref: BibleReference) {
  passagesStore.update((currentPassages) => {
    return currentPassages.filter(
      (p) =>
        !(
          p.langCode === ref.langCode &&
          p.bookCode === ref.bookCode &&
          p.startChapter === ref.startChapter &&
          p.startChapterVerseRef === ref.startChapterVerseRef &&
          p.endChapter === ref.endChapter &&
          p.endChapterVerseRef === ref.endChapterVerseRef
        )
    )
  })
}
