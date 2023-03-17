Python command-line implementation of [Netflix (`Fast.com`)](https://www.fast.com) speed-testing

<h1 align="center"><code>fast-cli</code></h1>

<p align="center">Fastest and highly accurate speedtesting client. Faster than <a href="https://www.fast.com">Netflix (<code>Fast.com</code>)</a> itself™</p>

### Why is this better than using the site?

- **You**, as a user, can control the time.
    - Less time, less precise but just.. quick.
- **You**, as a user, can select how much bytes this downloads.
    - Testing mobile connections without an abysmal amount of charge.
- **You**, as a user, can control exactly what is shown.
    - Minimalistic mode (`-m`) only shows you the live metrics.
    - Private mode (`-p`) shows you everything **but** your IPv4/IPv6 address and nearby server locations.
- Uses bytes as unit by default.
    - Usually, speed-tests use bits to make the user feel good but we both know you deserve more sadness. (`-8` flag to switch to bits.)
- Allows you to hide locations.
    - No need to care about blurring or cropping. Go wild with the private mode.
- Crazy accurate, as far as Python itself goes.
    - Unlike other speed-tests, this client **only** times when the bytes are being recieved.
- Fast initialisation.
    - This isn't Rust, but isn't a full blown browser either. Plus, this one does not even need to query the site, just the APIs.
- Supports uploading.
    - Better than nearly all of open-source projects in terms of code.
- Supports sharing.
    - Uses [Ookla Speedtest](https://www.speedtest.net/)'s sharing features (speed test is speed test everywhere!).


## Usage 

```console
$ fast-cli --help
Usage: fast-cli [OPTIONS]

Options:
  -dll, --download-limit INTEGER RANGE
                                  Download byte limit for testing. (0 for
                                  disabling)  [0<=x<26843545600]
  -ull, --upload-limit INTEGER RANGE
                                  Upload byte limit for testing. (0 for
                                  disabling)  [0<=x<26214400]
  -uc, --url-count INTEGER RANGE  Number of URLs to fetch.  [1<=x<=5]
  -c, --connections INTEGER       Number of connections to use. (5 is optimal)
  -t, --time-limit FLOAT          Time limit for testing.
  -8, --bits                      Use bits instead of bytes for speed
                                  calculations.
  -p, --private                   Use private mode for testing.
  -s, --share                     Share results after testing.
  -m, --minimalist                Go minimal with minimalistic mode.
  --help                          Show this message and exit.
```
