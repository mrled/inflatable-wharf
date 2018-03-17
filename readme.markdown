# Inflatable Wharf

A Docker container for handling ACME DNS challenges.

It's like... you can _dock_ there, after you, uhh, inflate it? Because some assembly is required? Yeah. Sorry about the name.

## Usage

This image is designed to be run directly,
especially while testing,
or as part of a Docker Swarm.

See the `Dockerfile` for a complete list of environment variables it will accept.

See below for examples.

### A note on checking out this repo

Like all shell scripts, the scripts in this file must have LF line endings (the Unix default),
not CRLF line endings (the Windows default).
On Windows, you should clone it like this to ensure the line endings are correct:

    git clone -c core.autocrlf=off git@github.com:mrled/inflatable-wharf.git

If you build the Docker container with CRLF line endings in the shell scripts,
you will see an error like this trying to run it:

    standard_init_linux.go:195: exec user process caused "no such file or directory"

### Notes on different authenticators

I don't have experience with most of the DNS authenticators supported by lego,
but I have used both `gandi` and `route53`.
In my experience, the `gandi` authenticator might take ~30 minutes,
while the `route53` authenticator was only takeing ~2 minutes.

### Example: running `inflatable-wharf` on the command line

This command will use the `inflatable-wharf` container to connect to the _staging_ API endpoint,
configure a Let's Encrypt account,
create a private key,
request that the ACME server signs the private key,
and ask the ACME server to verify ownership by a DNS challenge,
using Gandi's API to set and delete the challenge record.
It will save the Let's Encrypt account info
and public/private TLS keys to the `$legovolume` directory.

Note how we pass the `GANDI_API_KEY` directly,
even though it doesn't begin with `ACME_`.

    letsencrypt_email="you@example.com"
    domain="jenkins.example.com"
    gandi_api_key="yourapikey"
    lego_volume="$(pwd)/lego-temp-volume"
    mkdir -p "$lego_volume"

    docker run \
        --rm --interactive --tty \
        --env "GANDI_API_KEY=$gandi_api_key" \
        --env "ACME_LETSENCRYPT_EMAIL=$letsencrypt_email" \
        --env "ACME_DOMAIN=$domain" \
        --env "ACME_DNS_AUTHENTICATOR=gandi" \
        --env "ACME_SERVER=staging" \
        --env "ACME_FREQUENCY=monthly \
        --volume "${lego_volume}:/srv/inflatable-wharf" \
        mrled/inflatable-wharf:latest

### Example: running the `lego` container directly

This command will use the `lego` container to accomplish the same task as we did in `inflatable-wharf` above.

When I ran this, it took about 30 minutes.

    letsencrypt_email="you@example.com"
    domain="jenkins.example.com"
    gandi_api_key="yourapikey"
    lego_volume="$(pwd)/lego-temp-volume"
    mkdir -p "$lego_volume"

    docker run \
        --rm --interactive --tty \
        --env "GANDI_API_KEY=$gandi_api_key" \
        --volume "${lego_volume}:/.lego" \
        xenolf/lego \
            --accept-tos \
            --email "$letsencrypt_email" \
            --domains "$domain" \
            --dns gandi \
            --server "https://acme-staging.api.letsencrypt.org/directory" \
            run

### Example: using Docker swarm with `inflatable-wharf`

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

