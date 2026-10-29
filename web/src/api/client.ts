import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export const api = createClient<paths>({ baseUrl: '' })

type S = components['schemas']
export type RunSummary = S['RunSummary']
export type RunDetail = S['RunDetail']
export type MenuRow = S['MenuRow']
export type MenuReview = S['MenuReview']
export type BBox = S['BBox']
export type Outcome = S['Outcome']

/** Unwraps an openapi-fetch result or throws a readable error. */
export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request
  if (data === undefined) {
    const detail = (error as { detail?: unknown } | undefined)?.detail
    throw new Error(typeof detail === 'string' ? detail : `${response.status} ${response.statusText}`)
  }
  return data
}
