# Audited fallback notices

`logfire-api-5.4.0-LICENSE` is the unchanged MIT license obtained on 2026-10-31
from https://raw.githubusercontent.com/pydantic/logfire/v5.4.0/LICENSE.
The installed `logfire-api` 5.4.0 wheel declares MIT but omits its license file.
The backend collector uses this version-specific fallback only when that wheel
has no bundled notice. A new wheel version without a notice fails closed until
its corresponding upstream notice is reviewed; do not apply this file to another
version by renaming it.
