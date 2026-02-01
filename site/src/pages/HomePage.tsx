import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useCatalog, useStats } from '../hooks/useCatalog'
import type { CatalogEntry } from '../types/catalog'

type StatusFilter = 'all' | 'verified' | 'parseable' | 'failed'
type SourceFilter = 'all' | 'github' | 'seed' | 'sitemap' | 'commoncrawl'

export function HomePage() {
  const { entries, loading, error } = useCatalog()
  const { stats } = useStats()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')

  const filteredEntries = useMemo(() => {
    return entries.filter((entry) => {
      // Status filter
      if (statusFilter !== 'all' && entry.verification.status !== statusFilter) {
        return false
      }

      // Source filter
      if (sourceFilter !== 'all' && entry.provenance.source_type !== sourceFilter) {
        return false
      }

      // Search filter
      if (search) {
        const searchLower = search.toLowerCase()
        const matchesId = entry.id.toLowerCase().includes(searchLower)
        const matchesUrl = entry.file.url.toLowerCase().includes(searchLower)
        const matchesFilename = entry.file.filename?.toLowerCase().includes(searchLower)
        const matchesShells = entry.metadata?.shells?.some(
          (s) => s.id_short?.toLowerCase().includes(searchLower) || s.id.toLowerCase().includes(searchLower)
        )
        const matchesSubmodels = entry.metadata?.submodels?.some(
          (s) => s.id_short?.toLowerCase().includes(searchLower) || s.id.toLowerCase().includes(searchLower)
        )
        const matchesSemanticIds = entry.metadata?.semantic_ids?.some((id) =>
          id.toLowerCase().includes(searchLower)
        )

        if (!matchesId && !matchesUrl && !matchesFilename && !matchesShells && !matchesSubmodels && !matchesSemanticIds) {
          return false
        }
      }

      return true
    })
  }, [entries, search, statusFilter, sourceFilter])

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center">Loading catalog...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center text-red-600">Error loading catalog: {error}</div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard label="Total Files" value={stats.total_entries} />
          <StatCard label="Verified" value={stats.by_status.verified || 0} color="green" />
          <StatCard label="Parseable" value={stats.by_status.parseable || 0} color="yellow" />
          <StatCard label="Failed" value={stats.by_status.failed || 0} color="red" />
        </div>
      )}

      {/* Search and Filters */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="flex flex-col md:flex-row gap-4">
          <input
            type="text"
            placeholder="Search by ID, URL, filename, or semantic ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
          >
            <option value="all">All Statuses</option>
            <option value="verified">Verified</option>
            <option value="parseable">Parseable</option>
            <option value="failed">Failed</option>
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
          >
            <option value="all">All Sources</option>
            <option value="github">GitHub</option>
            <option value="seed">Seed</option>
            <option value="sitemap">Sitemap</option>
            <option value="commoncrawl">Common Crawl</option>
          </select>
        </div>
      </div>

      {/* Results count */}
      <p className="text-gray-600 mb-4">
        Showing {filteredEntries.length} of {entries.length} files
      </p>

      {/* Results Grid */}
      <div className="grid gap-4">
        {filteredEntries.slice(0, 50).map((entry) => (
          <EntryCard key={entry.id} entry={entry} />
        ))}
      </div>

      {filteredEntries.length > 50 && (
        <p className="text-center text-gray-500 mt-4">
          Showing first 50 results. Use search to narrow down.
        </p>
      )}
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  const colorClasses = {
    green: 'text-green-600',
    yellow: 'text-yellow-600',
    red: 'text-red-600',
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-2xl font-bold ${color ? colorClasses[color as keyof typeof colorClasses] : ''}`}>
        {value.toLocaleString()}
      </p>
    </div>
  )
}

function EntryCard({ entry }: { entry: CatalogEntry }) {
  const statusColors = {
    verified: 'bg-green-100 text-green-800',
    parseable: 'bg-yellow-100 text-yellow-800',
    failed: 'bg-red-100 text-red-800',
  }

  return (
    <Link
      to={`/asset/${encodeURIComponent(entry.id)}`}
      className="block bg-white rounded-lg shadow hover:shadow-md transition-shadow p-4"
    >
      <div className="flex justify-between items-start">
        <div className="flex-1 min-w-0">
          <h3 className="font-medium text-gray-900 truncate">
            {entry.file.filename || entry.id}
          </h3>
          <p className="text-sm text-gray-500 truncate">{entry.file.url}</p>
          {entry.metadata?.semantic_ids && entry.metadata.semantic_ids.length > 0 && (
            <p className="text-xs text-gray-400 mt-1 truncate">
              {entry.metadata.semantic_ids.slice(0, 3).join(', ')}
              {entry.metadata.semantic_ids.length > 3 && '...'}
            </p>
          )}
        </div>
        <div className="flex items-center space-x-2 ml-4">
          <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[entry.verification.status]}`}>
            {entry.verification.status}
          </span>
          <span className="text-xs text-gray-400">{entry.provenance.source_type}</span>
        </div>
      </div>
    </Link>
  )
}
