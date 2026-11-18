# Localhost TLS fixture

The certificate and private key in this directory are public test data generated for
the loopback HTTPS server. They are not credentials for any service. Never use this
key for deployment or add this certificate to a production trust store.

The certificate covers `localhost` and `127.0.0.1` and expires on 2036-10-19.
Tests pass an explicit verified TLS context for this fixture. A separate request proves
that environment-derived certificate trust cannot make it trusted implicitly.
