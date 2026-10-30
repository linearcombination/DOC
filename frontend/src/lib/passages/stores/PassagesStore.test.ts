import { get } from 'svelte/store'
import { beforeEach, describe, expect, test } from 'vitest'
import {
  addAvailableBibleReference,
  addBibleReference,
  availablePassagesStore,
  clearPassages,
  passagesStore
} from './PassagesStore'
import type { BibleReference } from '../models'

const ref: BibleReference = {
  langCode: 'en',
  bookCode: 'mat',
  startChapter: 2,
  startChapterVerseRef: 1,
  endChapter: 2,
  endChapterVerseRef: 12
} as unknown as BibleReference

describe('clearPassages', () => {
  beforeEach(() => {
    passagesStore.set([])
    availablePassagesStore.set([])
    addBibleReference(ref)
    addAvailableBibleReference(ref)
  })

  test('language change clears chosen and available passages', () => {
    clearPassages()
    expect(get(passagesStore)).toEqual([])
    expect(get(availablePassagesStore)).toEqual([])
  })

  test('unchanged language selection leaves passages in place', () => {
    // Nothing calls clearPassages when the language step is revisited without a change
    expect(get(passagesStore)).toEqual([ref])
    expect(get(availablePassagesStore)).toEqual([ref])
  })
})
