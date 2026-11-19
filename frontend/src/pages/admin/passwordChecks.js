// The password checks the browser can do before asking the server, shared by
// the Create account form (ADM-01) and Change password (ADM-05). The server
// checks everything again, including the common-password list and the
// person's own name and email (backend/accounts/passwords.py).

export const MIN_PASSWORD = 15
export const MAX_PASSWORD = 64

// Problems with a new password and its confirmation: { password?, confirmation? }
export function checkNewPassword(password, confirmation) {
  const errors = {}
  // Counted in characters as the server does, not in UTF-16 units
  const length = [...password].length

  if (!password) errors.password = 'Enter a password, or select Generate.'
  else if (length < MIN_PASSWORD)
    errors.password = `Use at least ${MIN_PASSWORD} characters. A short phrase works well.`
  else if (length > MAX_PASSWORD) errors.password = `Use at most ${MAX_PASSWORD} characters.`

  if (password && confirmation !== password) errors.confirmation = 'The passwords do not match.'

  return errors
}
