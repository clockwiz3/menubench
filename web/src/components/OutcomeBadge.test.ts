import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import OutcomeBadge from './OutcomeBadge.vue'

describe('OutcomeBadge', () => {
  it('always shows a text label, never color alone', () => {
    expect(mount(OutcomeBadge, { props: { outcome: 'wrong_name' } }).text()).toContain('Wrong item')
    expect(mount(OutcomeBadge, { props: { outcome: 'missed' } }).text()).toContain('Missed')
  })
})
