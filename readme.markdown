# Inflatable Wharf

A Docker container for handling ACME DNS challenges.

It's like... you can _dock_ there, after you, uhh, inflate it? Because some assembly is required? Yeah. Sorry about the name.

## Usage

This image is designed to be run directly,
especially while testing,
or as part of a Docker Swarm.

See the `Dockerfile` for a complete list of environment variables it will accept.

See below for examples.

### Example: running the container directly

This command will use the `lego` container to connect to the _staging_ API endpoint,
configure a Let's Encrypt account,
create a private key,
request that the ACME server signs the private key,
and ask the ACME server to verify ownership by a DNS challenge,
using Gandi's API to set and delete the challenge record.
It will save the Let's Encrypt account info
and public/private TLS keys to the `$legovolume` directory.

This assumes that you are using Gandi DNS and have a valid Gandi API key.

Note how we pass the `GANDI_API_KEY` directly,
even though it doesn't begin with `ACME_`.

When I ran this, it took about 30 minutes.

    letsencrypt_email="you@example.com"
    domain="jenkins.example.com"
    gandi_api_key="yourapikey"
    lego_volume="$(pwd)/lego-temp-volume"
    mkdir -p "$lego_volume"

    docker run \
        --rm \
        --interactive \
        --tty \
        --env "GANDI_API_KEY=$gandi_api_key" \
        --volume "${lego_volume}:/.lego" \
        xenolf/lego \
            --accept-tos \
            --email "$letsencrypt_email" \
            --domains "$domain" \
            --dns gandi \
            --server "https://acme-staging.api.letsencrypt.org/directory" \
            run

### Example: using Docker swarm

How to use `inflatable-wharf` with Docker Swarm

This assumes you are using Gandi DNS and have a valid Gandi API key.

Note how we are not passing a `GANDI_API_KEY` environment variable directly,
but instead keep the environment variable in the `lego_acme_env_file` secret.

`example.compose.yaml`:

    version: "3.2"
    services:

    inflatable-wharf:
      image: mrled/inflatable-wharf:latest
      deploy:
        replicas: 1
      environment:
        - ACME_LETSENCRYPT_EMAIL=you@example.com
        - ACME_DOMAIN=subdomain.example.com
        - ACME_DNS_AUTHENTICATOR=gandi
        - ACME_SERVER=production
        - ACME_FREQUENCY=monthly
        - ACME_SECRETS_ENV_FILE=/run/secrets/lego_acme_env_file
      secrets:
        - source: lego_acme_env_file
          target: lego_acme_env_file
          mode: 0444
      volumes:
        - certs:/srv/inflatable-wharf

    example-cert-user:
      image: some/image
      ports:
        - "80:8080"
        - "443:8443"
      volumes:
        - certs:/var/certs
      deploy:
        replicas: 1

    volumes:
      certs:

    secrets:
      lego_acme_env_file:
        file: ./lego-acme-secret-env.txt

`lego-acme-secret-env.txt`:

    GANDI_API_KEY=xxx

Finally, run this command to deploy the stack:

    docker stack deploy --compose-file example.compose.yml ExampleStackName

**Your service may not be available until the certs exist.**

`lego` can take 20-30 minutes to validate the DNS challenge
and receive the signed certificate from Let's Encrypt.

For example, if the image using your cert is the official Jenkins image,
the Swarm will spin that image up,
it will see that it cannot find its TLS certificates,
and will shut itself back down,
but once the certificates are available,
it will stay up.

You can view logs it by first getting service IDs:

    docker stack services ExampleStackName

Which might return output like this:

    ID                  NAME                       MODE                REPLICAS            IMAGE                           PORTS
    uvafm36cyz38        jenkins_jenkins            replicated          1/1                 jenkins/jenkins:lts             *:80->8080/tcp,*:443->8443/tcp
    vla3440dmlwn        jenkins_inflatable-wharf   replicated          1/1                 mrled/inflatable-wharf:latest   

And then grabbing the log for the service in question based on that service ID:

    # The -f argument to logs works like the -f argument to tail
    docker service logs -f uvafm36cyz38

(Note that `docker service logs` operates on _service_ IDs you get from `docker stack services`,
not _container_ IDs that you might get from `docker ps`)

## TO DO

- Do NOT renew cert on startup all the time
  - This is dangerous - what if the Docker container gets into a restart loop and gets me throttled by Let's Encrypt?
- Get an initial cert on startup if the existing cert does not exist
  - happening now
- Renew cert on startup if the existing cert is expiring before the next run from cron
  - https://stackoverflow.com/questions/21297853/how-to-determine-ssl-cert-expiration-date-from-a-pem-encoded-certificate#21297927
  - see end date: `openssl x509 -enddate -noout -in <cert file>`
  - check whether cert will expire in X seconds: `openssl x509 -checkend <number of seconds> -noout -in <cert file>`
  - Comparing dates would be much easier in a real language...
- Renew cert on startup if the cert exists but was issued by a different server (staging/production)
  - see the cert details including issuer: `openssl x509 -text -noout -in <signed cert>`
  - check whether cert was signed by a given CA: `openssl verify -verbose -CAFile <ca cert> <signed cer>`
  - Parsing openssl output would be much easier with Python,
    and maybe there are Python libraries that won't even require shelling out to openssl...
