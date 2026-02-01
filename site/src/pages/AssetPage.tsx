import { useParams, Link } from 'react-router-dom'
import { useEntry } from '../hooks/useCatalog'

export function AssetPage() {
  const { id } = useParams<{ id: string }>()
  const { entry, loading, error } = useEntry(id || '')

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center">Loading...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center text-red-600">Error: {error}</div>
      </div>
    )
  }

  if (!entry) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">Asset Not Found</h1>
          <Link to="/" className="text-primary-600 hover:underline">
            Back to catalog
          </Link>
        </div>
      </div>
    )
  }

  const statusColors = {
    verified: 'bg-green-100 text-green-800 border-green-200',
    parseable: 'bg-yellow-100 text-yellow-800 border-yellow-200',
    failed: 'bg-red-100 text-red-800 border-red-200',
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Link to="/" className="text-primary-600 hover:underline mb-4 inline-block">
        ← Back to catalog
      </Link>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex justify-between items-start">
            <div>
              <h1 className="text-xl font-bold text-gray-900">
                {entry.file.filename || 'Unknown File'}
              </h1>
              <p className="text-sm text-gray-500 font-mono mt-1">{entry.id}</p>
            </div>
            <span
              className={`px-3 py-1 rounded-full text-sm font-medium border ${statusColors[entry.verification.status]}`}
            >
              {entry.verification.status}
            </span>
          </div>
        </div>

        {/* File Info */}
        <Section title="File">
          <InfoRow label="URL">
            <a
              href={entry.file.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:underline break-all"
            >
              {entry.file.url}
            </a>
          </InfoRow>
          {entry.file.size_bytes && (
            <InfoRow label="Size">{formatBytes(entry.file.size_bytes)}</InfoRow>
          )}
          <InfoRow label="SHA256">
            <code className="text-sm bg-gray-100 px-2 py-1 rounded break-all">
              {entry.file.sha256}
            </code>
          </InfoRow>
        </Section>

        {/* Provenance */}
        <Section title="Provenance">
          <InfoRow label="Source">{entry.provenance.source_type}</InfoRow>
          {entry.provenance.source_ref && (
            <InfoRow label="Source Ref">{entry.provenance.source_ref}</InfoRow>
          )}
          {entry.provenance.license && (
            <InfoRow label="License">{entry.provenance.license}</InfoRow>
          )}
          <InfoRow label="Discovered">{formatDate(entry.provenance.discovered_at)}</InfoRow>
          {entry.provenance.last_verified_at && (
            <InfoRow label="Last Verified">{formatDate(entry.provenance.last_verified_at)}</InfoRow>
          )}
        </Section>

        {/* Verification */}
        <Section title="Verification">
          <InfoRow label="Status">
            <span className={`px-2 py-1 rounded text-sm ${statusColors[entry.verification.status]}`}>
              {entry.verification.status}
            </span>
          </InfoRow>
          {entry.verification.engine && (
            <InfoRow label="Engine">{entry.verification.engine}</InfoRow>
          )}
          {entry.verification.summary && (
            <InfoRow label="Summary">{entry.verification.summary}</InfoRow>
          )}
          {entry.verification.errors && entry.verification.errors.length > 0 && (
            <div className="mt-4">
              <p className="text-sm font-medium text-gray-700 mb-2">Errors:</p>
              <ul className="list-disc list-inside text-sm text-red-600 space-y-1">
                {entry.verification.errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </Section>

        {/* Metadata */}
        {entry.metadata && (
          <>
            {entry.metadata.shells && entry.metadata.shells.length > 0 && (
              <Section title="Asset Administration Shells">
                <div className="space-y-3">
                  {entry.metadata.shells.map((shell, i) => (
                    <div key={i} className="bg-gray-50 rounded p-3">
                      <p className="font-medium">{shell.id_short || 'Unnamed Shell'}</p>
                      <p className="text-sm text-gray-600 font-mono">{shell.id}</p>
                      {shell.global_asset_id && (
                        <p className="text-xs text-gray-500 mt-1">
                          Asset: {shell.global_asset_id}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {entry.metadata.submodels && entry.metadata.submodels.length > 0 && (
              <Section title="Submodels">
                <div className="space-y-3">
                  {entry.metadata.submodels.map((sm, i) => (
                    <div key={i} className="bg-gray-50 rounded p-3">
                      <p className="font-medium">{sm.id_short || 'Unnamed Submodel'}</p>
                      <p className="text-sm text-gray-600 font-mono">{sm.id}</p>
                      {sm.semantic_id && (
                        <p className="text-xs text-gray-500 mt-1">
                          Semantic ID: {sm.semantic_id}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {entry.metadata.semantic_ids && entry.metadata.semantic_ids.length > 0 && (
              <Section title="Semantic IDs">
                <div className="flex flex-wrap gap-2">
                  {entry.metadata.semantic_ids.map((id, i) => (
                    <span
                      key={i}
                      className="bg-gray-100 text-gray-700 px-2 py-1 rounded text-sm font-mono"
                    >
                      {id}
                    </span>
                  ))}
                </div>
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="px-6 py-4 border-b border-gray-200 last:border-b-0">
      <h2 className="text-lg font-semibold text-gray-900 mb-3">{title}</h2>
      {children}
    </div>
  )
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start py-2">
      <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{label}</span>
      <span className="text-sm text-gray-900 mt-1 sm:mt-0">{children}</span>
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(isoString: string): string {
  try {
    return new Date(isoString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return isoString
  }
}
