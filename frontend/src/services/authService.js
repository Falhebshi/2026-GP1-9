// Where the Login page signs a user in. FAKE for now: any email and
// password are accepted. When the backend is ready, only the inside of
// logIn() changes.
//
// PROPOSED CONTRACT (agree it with the backend team):
//   logIn({ email, password }) returns
//     { user: { id, name, email, role }, isSample }
//   or throws an Error whose message can be shown to the user as it is.
//
// To see the error messages, add ?demo=invalid or ?demo=error to the address.

export async function logIn({ email }) {
  await new Promise((resolve) => setTimeout(resolve, 600)) // stands in for the server

  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'invalid') throw new Error('Email or password is incorrect.')
  if (demo === 'error') throw new Error('The login service is not responding. Try again in a moment.')

  // Later: return (await fetch('/api/login', { method: 'POST', ... })).json()
  return { user: { id: 'u1', name: 'Traffic Engineer', email, role: 'engineer' }, isSample: true }
}
