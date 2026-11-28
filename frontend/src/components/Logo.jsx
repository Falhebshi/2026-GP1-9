import './Logo.css'

// The Jaadah wordmark: the name set in Plus Jakarta Sans ExtraBold.
// (The same wordmark as outlined SVG files, for the report and slides, is in
// src/assets/brand/.)
//
//   tone       "auto" (default) follows light / night mode
//              "dark" always the version for dark backgrounds, e.g. the
//              indigo panel on the Login page
//   className  set --logo-size on it to size the wordmark (default 26px)
function Logo({ tone = 'auto', className = '' }) {
  return <span className={`logo logo-${tone} ${className}`}>Jaadah</span>
}

export default Logo
