# Localhost TLS fixture

`localhost-cert.pem` and `localhost-key.pem` are not committed. The test run creates them
here on first use (`scripts/localhost_tls.py`, needs `openssl` on `PATH`), and `.gitignore`
keeps them out of the repo. To recreate them, delete both files and run the tests again.

They are a self-signed certificate and key for `localhost` and `127.0.0.1`, used only by
the loopback HTTPS server that stands in for the provider. They are not credentials for any
service. Never use this key for deployment or add this certificate to a production trust
store.

Tests pass an explicit verified TLS context for this fixture. A separate request proves
that environment-derived certificate trust cannot make it trusted implicitly.
