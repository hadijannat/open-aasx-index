import { useState, useEffect } from 'react'
import type { CatalogEntry, CatalogStats } from '../types/catalog'

const CATALOG_URL = '/catalog.json'
const STATS_URL = '/stats.json'

export function useCatalog() {
  const [entries, setEntries] = useState<CatalogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(CATALOG_URL)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => {
        setEntries(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  return { entries, loading, error }
}

export function useStats() {
  const [stats, setStats] = useState<CatalogStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(STATS_URL)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => {
        setStats(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  return { stats, loading, error }
}

export function useEntry(id: string) {
  const { entries, loading, error } = useCatalog()
  const entry = entries.find((e) => e.id === id)
  return { entry, loading, error }
}
