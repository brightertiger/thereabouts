The localhost certificate and PKCS#8 key are public test fixtures, generated
with OpenSSL for 127.0.0.1 only. Tests explicitly trust this certificate in
a private ureq agent. Production agents retain ordinary WebPKI verification.
This key is never used by any release service.
