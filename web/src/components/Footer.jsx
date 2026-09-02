import { fmtDateTime } from '../lib/format.js'

export default function Footer({ model }) {
  const zip = model.home?.zip || '77479'
  return (
    <footer className="foot">
      <b>Caveats</b>
      <ul>
        <li>Prices are the dealers' advertised prices and exclude tax, title, registration and dealer fees.</li>
        <li>
          CarMax shipping is CarMax's own transfer quote to {zip} at scrape time; "effective price" = list price + that quote. Nothing is added for local dealers.
        </li>
        <li>Medians are computed over active listings only, per model year and trim, in the selected price mode. Buckets with a single car are marked thin.</li>
        <li>Trims are parsed from listing text (a "?" marks a low-confidence guess); MSRP is the base price for the model year, so discount % ignores options.</li>
        <li>Verify price, mileage, availability and history on the dealer page before acting on anything here.</li>
      </ul>
      <div>
        Data generated {fmtDateTime(model.generatedAt)} ·{' '}
        <a href="https://github.com/sanjulseth44-eng/tesla-highland-tracker" target="_blank" rel="noopener noreferrer">
          Scraper &amp; dashboard source on GitHub ↗
        </a>
      </div>
    </footer>
  )
}
