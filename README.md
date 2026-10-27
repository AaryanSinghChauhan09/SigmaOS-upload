    # SigmaOS-upload

    File upload / share service client

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/mintupload

    ## Design principles applied
    - **Defensive Programming**
- **Fail-Fast**
- **Separation of Concerns**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `upload-plan, targets, size-limit, history`

    ```
    $ sigma-upload targets
transfer  PUT   https://transfer.sh/{name}   max=5120M
$ sigma-upload size-limit 10M
10000000 bytes
$ sigma-upload upload-plan report.pdf --target transfer --limit 50M
curl --upload-file report.pdf https://transfer.sh/report.pdf
$ sigma-upload history --store history.jsonl
report.pdf -> transfer (71234 bytes) ok

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
