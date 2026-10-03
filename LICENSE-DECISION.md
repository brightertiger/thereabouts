# Licence decision pending

No code LICENSE file has been added. The owner must choose a code licence and
confirm data redistribution notices before publication. npm currently declares
UNLICENSED; Python metadata makes no open-source licence claim.

The release dataset declares ODbL 1.0. Its DATA_LICENSES.md and manifest.sources
retain per-source licences, attribution, URLs and pins. The database obligations
and source-specific notices remain relevant regardless of the code licence.
Distributing code under MIT or Apache-2.0 does not relicense the data.
Review the assembled release notices and source restrictions before redistributing
any dataset or pack.

Code options for the owner:

| Choice | Practical implications |
| --- | --- |
| MIT | Short permissive licence; retain copyright and permission notices. It has no express patent-grant clause. |
| Apache-2.0 | Permissive licence with an express contributor patent grant and patent-litigation termination terms; retain required notices and mark modifications. It does not grant trademark rights. |

Both choices permit commercial use and include warranty disclaimers. Neither
choice removes third-party dependency licences or the separate database terms.
Before choosing, review contributor ownership, patent policy and the licences of
bundled Rust, Python and npm dependencies. Decide whether an Apache NOTICE file is
needed for the selected distribution.

After the decision, add the chosen licence text, update package metadata and
notices, and approve release artifacts. CI environments and registry trusted
publishers must also be configured by the owner. No licence choice or publication
has been made on the owner's behalf.
