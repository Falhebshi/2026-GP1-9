import { Link, useNavigate } from 'react-router-dom'
import BrandMark from '../components/BrandMark'
import Button from '../components/Button'
import NavBar from '../components/NavBar'
import './Welcome.css'

// The first page people see, at "/". It has no data, so it has no service:
// everything here is fixed text.
//
// Sections, top to bottom (follows the Figma "Welcome Page" frame):
//   header   the shared NavBar; on "/" it shows only the brand
//   hero     headline, intro, Log in button, desktop monitor picture
//   about    About Jaadah text, three points, "How Jaadah works" steps,
//            mission statement and three goals
//   footer   brand, social links, copyright

// TODO: put the real addresses here. A link without a url is not shown.
const SOCIAL_LINKS = [
  { label: 'LinkedIn', url: '' },
  { label: 'X (Twitter)', url: '' },
  { label: 'YouTube', url: '' },
]

const CURRENT_YEAR = new Date().getFullYear()

function Welcome() {
  const navigate = useNavigate()
  const socialLinks = SOCIAL_LINKS.filter((link) => link.url)

  return (
    <div className="welcome">
      <NavBar />

      <main className="welcome-main">
        <section className="welcome-hero">
          <div className="welcome-hero-text">

            <h1 className="welcome-title">
              Understand traffic.
              <br />
              <span className="welcome-title-ombre">
                {/* &nbsp; keeps "what's next." together on one line */}
                Anticipate what&rsquo;s&nbsp;next.
              </span>
            </h1>

            <p className="welcome-intro">
              Jaadah helps traffic professionals monitor conditions, detect
              emerging problems, and evaluate possible interventions through
              one connected digital twin platform.
            </p>

            <Button
              className="welcome-login"
              onClick={() => navigate('/login')}
            >
              Log in
              <span aria-hidden="true">→</span>
            </Button>

            <p className="welcome-login-note">
              Access Jaadah with your authorized account.
            </p>
          </div>

          <DesktopPicture />
        </section>

        <section
          id="welcome-about"
          className="welcome-about"
          aria-labelledby="welcome-about-title"
        >
          <div className="welcome-about-inner">
            <div className="welcome-about-text">
              <p className="welcome-about-eyebrow">Who we are</p>
              <h2 id="welcome-about-title" className="welcome-about-title">
                About Jaadah
              </h2>

              <p>
                Jaadah brings traffic monitoring, simulation, forecasting, and
                intervention analysis together in one place.
              </p>
              <p>
                It gives engineers a clearer view of how an intersection is
                performing now, how conditions may develop, and how proposed
                changes could affect traffic before they are applied on the
                road.
              </p>

              <ul className="welcome-promises">
                {PROMISES.map((promise) => (
                  <li key={promise.title} className="welcome-promise">
                    <span className="welcome-promise-icon" aria-hidden="true">
                      <LineIcon name={promise.icon} />
                    </span>
                    <span>
                      <strong className="welcome-promise-title">
                        {promise.title}
                      </strong>
                      <span className="welcome-promise-text">{promise.text}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="welcome-flow-card">
              <p className="welcome-flow-title">How Jaadah works</p>
              <ol className="welcome-flow">
                {STEPS.map((step, i) => (
                  <li key={step.title} className="welcome-flow-step">
                    <span className="welcome-flow-icon" aria-hidden="true">
                      <LineIcon name={step.icon} />
                    </span>
                    <div>
                      <p className="welcome-flow-step-title">
                        <span className="welcome-flow-number">{i + 1}</span>
                        {step.title}
                      </p>
                      <p className="welcome-flow-step-text">{step.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>

          <div className="welcome-mission">
            <div className="welcome-mission-inner">
              <p className="welcome-mission-label">Our mission</p>
              <p className="welcome-mission-text">
                Turn traffic data into{' '}
                <span className="welcome-mission-ombre">clearer decisions.</span>
              </p>

              <ul className="welcome-goals">
                {GOALS.map((goal) => (
                  <li key={goal.title} className="welcome-goal">
                    <span className="welcome-goal-icon" aria-hidden="true">
                      <LineIcon name={goal.icon} />
                    </span>
                    <span className="welcome-goal-title">{goal.title}</span>
                    <span className="welcome-goal-text">{goal.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </main>

      <footer className="welcome-footer">
        <div className="welcome-footer-inner">
          <div className="welcome-footer-brand">
            <Link to="/" className="welcome-brand">
              <BrandMark />
              Jaadah
            </Link>
            <p className="welcome-footer-tagline">
              Traffic intelligence and decision support for Riyadh.
            </p>
          </div>

          {/* Only social links here. Each appears once its url is filled in. */}
          {socialLinks.length > 0 && (
            <nav className="welcome-footer-links" aria-label="Social links">
              {socialLinks.map((link) => (
                <a
                  key={link.label}
                  href={link.url}
                  className="welcome-footer-link"
                  target="_blank"
                  rel="noreferrer"
                >
                  {link.label}
                </a>
              ))}
            </nav>
          )}
        </div>

        <p className="welcome-footer-copy">
          © {CURRENT_YEAR} Jaadah. All rights reserved.        
        </p>
      </footer>
    </div>
  )
}

// The three points beside the About Jaadah text.
const PROMISES = [
  {
    icon: 'sensor',
    title: 'Monitor',
    text: 'Review traffic conditions and key performance indicators.',
  },
  {
    icon: 'forecast',
    title: 'Forecast',
    text: 'See how traffic may develop over the next 15 to 60 minutes.',
  },
  {
    icon: 'compare',
    title: 'Evaluate',
    text: 'Compare proposed interventions against existing conditions.',
  },
]

// The three goals under the mission statement.
const GOALS = [
  {
    icon: 'sensor',
    title: 'See the current picture',
    text: 'Understand where performance is deteriorating and why.',
  },
  {
    icon: 'forecast',
    title: 'Stay ahead',
    text: 'Identify possible traffic problems before they become more severe.',
  },
  {
    icon: 'twin',
    title: 'Test with confidence',
    text: 'Explore the expected effect of an intervention before applying it in the real network.',
  },
]

// The "How Jaadah works" steps on the right of About Jaadah.
const STEPS = [
  {
    icon: 'sensor',
    title: 'Observe',
    text: 'Traffic and signal data describe current operating conditions.',
  },
  {
    icon: 'twin',
    title: 'Simulate',
    text: 'A digital twin reproduces traffic movement in the study area.',
  },
  {
    icon: 'chart',
    title: 'Analyze',
    text: 'Performance indicators and forecasts highlight where problems may develop.',
  },
  {
    icon: 'compare',
    title: 'Compare',
    text: 'Potential interventions are tested against the baseline before implementation.',
  },
]

// Small line icons for About Jaadah and the mission. Drawn here so they take the color of the
// text around them (currentColor). Used only on this page.
function LineIcon({ name }) {
  const shapes = {
    sensor: (
      <>
        <circle cx="12" cy="12" r="2.5" />
        <path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14" />
      </>
    ),
    twin: (
      <>
        <rect x="3" y="4" width="18" height="12" rx="2" />
        <path d="M8 20h8M12 16v4M7 12l3-3 2 2 5-4" />
      </>
    ),
    forecast: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3.5 2" />
      </>
    ),
    // Bars of a chart
    chart: <path d="M4 20h16M7 16v-5M12 16V7M17 16v-8" />,
    // Two options side by side, with arrows between them
    compare: (
      <>
        <rect x="3" y="5" width="7" height="14" rx="1.5" />
        <rect x="14" y="5" width="7" height="14" rx="1.5" />
        <path d="M10 9.5h4M12.5 8l1.5 1.5-1.5 1.5M14 14.5h-4M11.5 13 10 14.5l1.5 1.5" />
      </>
    ),
  }

  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {shapes[name]}
    </svg>
  )
}

// Used only on this page, so it stays in this file.
const SCREEN_CARDS = [
  { label: 'Live traffic', value: 'LOS C', active: true },
  { label: 'Forecast', value: '+30 min' },
  { label: 'Alerts', value: '3 active' },
]

const SCREEN_MENU = ['Overview', 'Current', 'Forecast', 'Alerts']

// Each row: how long its grey line is, and its status pill.
const SCREEN_ROWS = [
  { line: 70, pill: 'Current', type: 'current' },
  { line: 52, pill: 'Forecast', type: 'forecast' },
  { line: 62, pill: 'Pattern', type: 'pattern' },
]

function DesktopPicture() {
  return (
    <div className="welcome-desktop" aria-hidden="true">
      <div className="welcome-monitor">
        <div className="welcome-screen">
          <div className="welcome-screen-browser">
            <span className="welcome-screen-dots">
              <i />
              <i />
              <i />
            </span>
            <span className="welcome-screen-address">
              <i />
            </span>
          </div>

          <div className="welcome-screen-app">
            <div className="welcome-screen-menu">
              <div className="welcome-screen-logo">
                <span className="welcome-screen-logo-mark" />
                <span className="welcome-screen-line welcome-screen-line-strong" />
              </div>
              {SCREEN_MENU.map((item, i) => (
                <div
                  key={item}
                  className={`welcome-screen-menu-item ${
                    i === 0 ? 'welcome-screen-menu-item-active' : ''
                  }`}
                >
                  <span className="welcome-screen-menu-box" />
                  {item}
                </div>
              ))}
            </div>

            <div className="welcome-screen-content">
              <div className="welcome-screen-top">
                <div>
                  <p className="welcome-screen-heading">Network overview</p>
                  <span className="welcome-screen-line welcome-screen-line-sub" />
                </div>
                <div className="welcome-screen-user">
                  <span className="welcome-screen-line" />
                  <span className="welcome-screen-avatar" />
                </div>
              </div>

              <div className="welcome-screen-cards">
                {SCREEN_CARDS.map((card) => (
                  <div
                    key={card.label}
                    className={`welcome-screen-card ${
                      card.active ? 'welcome-screen-card-active' : ''
                    }`}
                  >
                    <p className="welcome-screen-card-label">{card.label}</p>
                    <span className="welcome-screen-card-value">{card.value}</span>
                  </div>
                ))}
              </div>

              <div className="welcome-screen-list">
                <div className="welcome-screen-list-head">
                  <p className="welcome-screen-list-title">Recent alerts</p>
                  <span className="welcome-screen-line" />
                </div>
                {SCREEN_ROWS.map((row) => (
                  <div key={row.pill} className="welcome-screen-row">
                    <span
                      className={`welcome-screen-row-icon welcome-screen-${row.type}`}
                    />
                    <span
                      className="welcome-screen-line welcome-screen-row-line"
                      // Inline style only passes the number into CSS.
                      style={{ '--w': `${row.line}%` }}
                    />
                    <span
                      className={`welcome-screen-pill welcome-screen-${row.type}`}
                    >
                      {row.pill}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="welcome-stand-neck" />
      <div className="welcome-stand-foot" />
    </div>
  )
}

export default Welcome
