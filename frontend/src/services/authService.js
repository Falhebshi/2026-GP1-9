// How the Login page signs a user in.
//
// For now it is FAKE: any email and password are accepted. When the backend
// is ready, only the inside of logIn() changes (it will call the server);
// the Login page stays the same, as long as the result keeps this shape.
//
//
//   logIn({ email, password, remember })
//
//   On success it returns:
//     {
//       user: {
//         id: 'u1',
//         name: 'Traffic Engineer',
//         email: 'name@organization.gov.sa',
//         role: 'engineer',
//       },
//       isSample: true,          true only while this is fake
//     }
//
//   On failure it throws an Error whose message can be shown to the user
//   as it is, for example "Email or password is incorrect."
//
// The real version will also keep the session (a cookie or token, decided
// with the backend). Pages do not need to know how.

// Gives back the signed-in user. It is "async" because the real version
// will wait for the server; the fake version waits a moment to behave the
// same way.
export async function logIn({ email, password, remember }) {
  await wait(600) // the real version waits for the server

  //   ?demo=invalid   to see the "wrong email or password" message
  //   ?demo=error     to see the "service not responding" message
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'invalid') throw new Error('Email or password is incorrect.')
  if (demo === 'error') {
    throw new Error('The sign-in service is not responding. Try again in a moment.')
  }

  // The fake version does not check the password or use "remember".
  // Later: return (await fetch('/api/login', { method: 'POST', ... })).json()
  void password
  void remember

  return {
    user: { id: 'u1', name: 'Traffic Engineer', email, role: 'engineer' },
    isSample: true,
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
