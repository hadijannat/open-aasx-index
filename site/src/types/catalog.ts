export interface CatalogEntry {
  id: string
  file: {
    url: string
    size_bytes?: number
    sha256: string
    filename?: string
  }
  provenance: {
    source_type: 'github' | 'seed' | 'sitemap' | 'commoncrawl'
    source_ref?: string
    license?: string
    discovered_at: string
    last_verified_at?: string
  }
  verification: {
    status: 'verified' | 'parseable' | 'failed'
    engine?: string
    exit_code?: number
    summary?: string
    errors?: string[]
  }
  metadata?: {
    shells?: Array<{
      id_short?: string
      id: string
      global_asset_id?: string
    }>
    submodels?: Array<{
      id_short?: string
      id: string
      semantic_id?: string
    }>
    semantic_ids?: string[]
  }
}

export interface CatalogStats {
  total_entries: number
  by_status: Record<string, number>
  by_source: Record<string, number>
  top_semantic_ids: Record<string, number>
  unique_semantic_ids: number
}
