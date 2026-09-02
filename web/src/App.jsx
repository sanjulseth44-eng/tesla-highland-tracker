import { useEffect, useMemo, useState } from 'react'
import { useUrlState } from './lib/urlState.js'
import { useMediaQuery } from './lib/useMedia.js'
import { buildModel } from './lib/model.js'
import { applyFilters, sortListings } from './lib/filters.js'
import Header from './components/Header.jsx'
import Filters from './components/Filters.jsx'
import MarketPanel from './components/MarketPanel.jsx'
import PriceScatter from './components/PriceScatter.jsx'
import Listings from './components/Listings.jsx'
import ChangeLog from './components/ChangeLog.jsx'
import MsrpTable from './components/MsrpTable.jsx'
import Footer from './components/Footer.jsx'

const DATA_URL = `${import.meta.env.BASE_URL}data/latest.json`

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    fetch(DATA_URL, { cache: 'no-store' })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} while loading ${DATA_URL}`)
        return r.json()
      })
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e))
    return () => {
      alive = false
    }
  }, [])

  const [state, patch, reset] = useUrlState()
  const narrow = useMediaQuery('(max-width: 759px)')
  const view = state.view || (narrow ? 'cards' : 'table')
  const mode = state.eff ? 'effective' : 'list'

  const model = useMemo(() => (data ? buildModel(data, mode) : null), [data, mode])
  const rows = useMemo(() => (model ? sortListings(applyFilters(model.listings, state), state.sort, state.dir) : []), [model, state])

  if (error) {
    return (
      <div className="wrap">
        <div className="card empty">
          Could not load listing data ({error.message}). Run the scraper, then <code>npm run build</code> or <code>npm run dev</code> again.
        </div>
      </div>
    )
  }
  if (!model) {
    return (
      <div className="wrap">
        <div className="loading">Loading listings…</div>
      </div>
    )
  }

  return (
    <div className="wrap">
      <Header model={model} />
      <Filters state={state} patch={patch} reset={reset} model={model} shown={rows.length} total={model.listings.length} />
      <div className="grid2">
        <MarketPanel buckets={model.buckets} mode={mode} />
        <PriceScatter rows={rows} mode={mode} />
      </div>
      <Listings rows={rows} view={view} state={state} patch={patch} mode={mode} sourceColors={model.sourceColors} home={model.home} />
      <ChangeLog model={model} />
      <MsrpTable msrp={model.msrp} notes={model.msrpNotes} />
      <Footer model={model} />
    </div>
  )
}
