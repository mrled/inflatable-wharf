#!/bin/sh
# Perforated cardboard is the. uhh. the entry point. For a box of Lego.
# Sorry

set -e
set -u

addgroup -g "$ACME_GROUP_ID" -S "$ACME_USER"
adduser -S -u "$ACME_USER_ID" -G "$ACME_USER" -s /bin/sh -h "$ACME_DIR" "$ACME_USER"

# Take in a line from `env`, like "ACME_WHATEVER=hahaha"
# If it starts with ACME_,
# or if it is found in the output of `lego dnshelp`,
# return true; otherwise return false.
dnshelp=$(lego dnshelp)
is_lego_dns_var() {
    varname="${1%%=*}"
    if echo "$varname" | grep -q '^ACME_'
    then
        return 0
    elif
        echo "$varname" | grep '[A-Z]' | grep '^\([A-Z]*_*\)*$' >/dev/null &&
        printf "$dnshelp" | grep -q "\b$varname\b"
    then
        return 0
    else
        return 1
    fi
}

# NOTE: this is a magic path used in all other scripts like lego-box.sh
lego_box_env_file=/etc/lego-box-environment

# Save all relevant environment variables here,
# then read this file in the legobox script,
# because they aren't in scope when running that script from cron or su
echo "" > "$lego_box_env_file"
chmod 644 "$lego_box_env_file"
for envline in $(env); do
    if test "$envline" && is_lego_dns_var "$envline"; then
        echo "$envline" >> "$lego_box_env_file"
    fi
done

echo "Saved environment to '$lego_box_env_file':"
cat "$lego_box_env_file" | sed 's/^/  /g'

legoboxpath="/usr/local/bin/lego-box.sh"
cron01min='* * * * *'
cron30day='* * 1 * *'

# Configure the crontab based on the frequency given by the environment
# Note that when we do 'crontab -' below, this *replaces* the existing crontab
# for our user; good in case we 'docker run' the container more than once
runonce=1
case "$ACME_FREQUENCY" in
    monthly) crontab="$cron30day $legoboxpath" ;;
    devel) crontab="$cron01min $legoboxpath --whatif"; runonce= ;;
    once) crontab="" ;;
    *) echo "Unknown value for ACME_FREQUENCY '$ACME_FREQUENCY'"; exit 1;;
esac

# Make sure logfile permissions are ok
touch "$ACME_LOGFILE"
chown "$ACME_USER:$ACME_USER" "$ACME_LOGFILE"

# Show whatif at first
"$legoboxpath" --whatif

# Run once
test "$runonce" && "$legoboxpath"

if test "$crontab"; then
    echo "Setting crontab:"
    echo "$crontab"
    echo "$crontab" | crontab -

    # Set the cron daemon to run in the background
    crond -b # -L "$ACME_DIR/crond.log"
    # Tail the ACME logfile forever
    tail -f "$ACME_LOGFILE"
else
    # Just echo a message and exit
    echo "No crontab to set"
fi
