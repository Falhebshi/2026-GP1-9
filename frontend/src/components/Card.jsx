import './Card.css'

// A white bordered panel.
//
//   title      text shown at the top (optional)
//   action     anything to show on the right of the title, such as a Badge,
//              a Select or a small Button (optional)
//   floating   adds a shadow, for panels that sit on top of the map
//
// Whatever you put between <Card> and </Card> becomes the body.
function Card({ title, action, floating = false, className = '', children }) {
  const classes = `card ${floating ? 'card-floating' : ''} ${className}`

  return (
    <section className={classes}>
      {(title || action) && (
        <header className="card-header">
          {title && <h2 className="card-title">{title}</h2>}
          {action && <div className="card-action">{action}</div>}
        </header>
      )}

      {children}
    </section>
  )
}

export default Card