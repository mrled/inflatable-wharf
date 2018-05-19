# xenolf/lego is based on alpine
FROM xenolf/lego:latest
LABEL maintainer "me@micahrl.com"

# An email address to send to Let's Encrypt
# You don't need to set up an account ahead of time; lego can do it for you
ENV ACME_LETSENCRYPT_EMAIL you@example.com

# The domain to create/renew the certificate for
ENV ACME_DOMAIN example.com

# The name of the DNS provider
# NOTE: You also must pass variables for your DNS provider credentials,
# such as an API access key and/or secret
# Run this command for more information about each specific provider:
#   docker run xenolf/lego:latest dnshelp
ENV ACME_DNS_AUTHENTICATOR manual

# If this is "staging", use the staging server
# If it's any other value, use the production server
ENV ACME_LETSENCRYPT_SERVER staging

# NOTE: This MUST match the uid of the container that will consume the certs
# For example, if you are using an apache container,
# this will need to match the UID that runs apache
# (which may be root)
# NOTE: We do not use a USER statement or create the user in the Dockerfile,
# because we accept these variables and create the user at container runtime
# to ensure correct permissions of certificate files
ENV ACME_USER_ID 1000
ENV ACME_GROUP_ID 1000

RUN true \
    && apk update \
    && apk add \
        # Our init system
        dumb-init \
        # Useful to have in the image for debugging, but not used in the code
        openssl \
        # 🐍
        python3 \
        \
        # For compiling the cryptography module
        gcc \
        libffi-dev \
        musl-dev \
        openssl-dev \
        python3-dev \
        \
    && python3 -m ensurepip \
    && python3 -m pip install -U pip \
    && python3 -m pip install \
        cryptography \
    && true

# REMINDER: Adjust permissions and set volume contents *before* declaring the volume
VOLUME /srv/inflatable-wharf

COPY ["inflwh.py", "/usr/local/bin/"]
RUN chmod 755 /usr/local/bin/inflwh.py

ENTRYPOINT ["/usr/bin/dumb-init", "--", "/usr/local/bin/inflwh.py"]
