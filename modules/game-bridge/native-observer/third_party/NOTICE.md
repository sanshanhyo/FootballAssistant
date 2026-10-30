# Dobby dependency notice

This observer dynamically uses a host-supplied Dobby library. No Dobby binary is
included in this source directory or copied into its build artifacts.

Source repository: https://github.com/BepInEx/Dobby

Fixed source reference: `9d271803881f467aabfc24593c7dcaeb710fe861`.

License: Apache License, Version 2.0. A complete copy is in `Dobby-LICENSE`.

The dependency's public Prepare/Commit function declarations are implemented by
that fixed API. This project does not copy the Instrument RegisterContext layout
from a different version. The local binary is identified by SHA-256
`0cab79106f5b309409fd752ea5fe85e74c4b0c04b35d6508d5c2556bc297bac6`
and reports `Dobby-20260703-9d27180`. Its complete build provenance beyond this
reference remains unverified.

No Dobby source modifications are made here. Preserve its license and any
applicable upstream notices when distributing a dependency binary separately.
