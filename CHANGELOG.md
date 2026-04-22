# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0](https://github.com/ben-ranford/cellin/compare/v0.3.0...v0.4.0) (2026-04-22)


### Features

* **cli:** eval backend parameterisation and DreamDiff inspect/rollback CLI ([#165](https://github.com/ben-ranford/cellin/issues/165) [#167](https://github.com/ben-ranford/cellin/issues/167)) ([#183](https://github.com/ben-ranford/cellin/issues/183)) ([219761a](https://github.com/ben-ranford/cellin/commit/219761a39a09285d4943564b4e8dabd00a9e1de2))
* **dreaming:** list_by, half_life decay archival, VectorStore.delete ([#162](https://github.com/ben-ranford/cellin/issues/162) [#163](https://github.com/ben-ranford/cellin/issues/163) [#164](https://github.com/ben-ranford/cellin/issues/164)) ([#188](https://github.com/ben-ranford/cellin/issues/188)) ([d29cc0c](https://github.com/ben-ranford/cellin/commit/d29cc0cb79733b337a8d7d10677548a9bbe5ec05))
* **ingest:** audio/video adapters, UnsupportedModalityError, CAUSED_BY/DERIVED_FROM edges ([#166](https://github.com/ben-ranford/cellin/issues/166) [#169](https://github.com/ben-ranford/cellin/issues/169)) ([#181](https://github.com/ben-ranford/cellin/issues/181)) ([1daefcd](https://github.com/ben-ranford/cellin/commit/1daefcdfb9c5785f075d3e01c674b5c2692b4588))
* **retrieval:** access_count writeback, wire representation_store, add ranker/retriever plugins ([#160](https://github.com/ben-ranford/cellin/issues/160) [#161](https://github.com/ben-ranford/cellin/issues/161) [#168](https://github.com/ben-ranford/cellin/issues/168)) ([#182](https://github.com/ben-ranford/cellin/issues/182)) ([38d10fb](https://github.com/ben-ranford/cellin/commit/38d10fb9373bf4ded3ea81bc2de2b3998c6b7c9f))
* **stores:** add edge-by-src/tgt index to Redis backend — O(degree) neighbors() ([#151](https://github.com/ben-ranford/cellin/issues/151)) ([#178](https://github.com/ben-ranford/cellin/issues/178)) ([a3b1035](https://github.com/ben-ranford/cellin/commit/a3b1035eb301725c544499fb7db2b3bc2aabf59d))


### Bug Fixes

* **dreaming:** contradiction stale ref, dedup N+1, tokenize dedup, graph write-amplification ([#172](https://github.com/ben-ranford/cellin/issues/172)) ([92ddac0](https://github.com/ben-ranford/cellin/commit/92ddac02b2fdb9b17ba1780ba5654d837a05b392))
* **ranking:** normalise WeightProfile factor weights ([#148](https://github.com/ben-ranford/cellin/issues/148)) ([#170](https://github.com/ben-ranford/cellin/issues/170)) ([6379db5](https://github.com/ben-ranford/cellin/commit/6379db5cc27cff0b034b8c9b6fab1712a9e3729a))


### Refactors

* **runtime:** replace 25 _build_* functions with table-driven backend registry ([#159](https://github.com/ben-ranford/cellin/issues/159)) ([#180](https://github.com/ben-ranford/cellin/issues/180)) ([b035a3f](https://github.com/ben-ranford/cellin/commit/b035a3f99cffadd12be186b359993847675752b0))
* **stores:** collapse Neo4j/Memgraph facades into shared wrapper ([#158](https://github.com/ben-ranford/cellin/issues/158)) ([#177](https://github.com/ben-ranford/cellin/issues/177)) ([609f4a8](https://github.com/ben-ranford/cellin/commit/609f4a8a426d27928b62973e5247ece59a5938e5))
* **stores:** extract _RemoteVectorBackendBase — eliminate 6 copy-pasted patterns ([#157](https://github.com/ben-ranford/cellin/issues/157)) ([#179](https://github.com/ben-ranford/cellin/issues/179)) ([6029175](https://github.com/ben-ranford/cellin/commit/60291757f2fefd82dc7252cbd7b45600fe73eae0))

## [0.3.0](https://github.com/ben-ranford/cellin/compare/v0.2.0...v0.3.0) (2026-04-08)


### Features

* add remote vector backends for qdrant weaviate pinecone milvus redis ([#92](https://github.com/ben-ranford/cellin/issues/92)) ([f161451](https://github.com/ben-ranford/cellin/commit/f1614516c5c334b577ee775bc5966ece84d4888a))
* add vector store abstraction and hybrid retrieval ([#89](https://github.com/ben-ranford/cellin/issues/89)) ([cecc921](https://github.com/ben-ranford/cellin/commit/cecc921489f057c63ffee3544d840d7d8c7a03db))
* **release:** automate rolling dev previews ([#82](https://github.com/ben-ranford/cellin/issues/82)) ([fdf490c](https://github.com/ben-ranford/cellin/commit/fdf490c8ccd3d6e93942ca4f08dbaaa1b12f7d27))
* **runtime:** register storage backends and setup flows ([#94](https://github.com/ben-ranford/cellin/issues/94)) ([bf24a7e](https://github.com/ben-ranford/cellin/commit/bf24a7e99c15432d07232b1a733232c85b2e5e0d))
* **storage:** add first-party SQL memory and graph backends ([#90](https://github.com/ben-ranford/cellin/issues/90)) ([5fe1ba2](https://github.com/ben-ranford/cellin/commit/5fe1ba2b9218bc8fe5d3cb345ccf78298b4bd556))
* **storage:** add graph-native graph backends ([#93](https://github.com/ben-ranford/cellin/issues/93)) ([360c64c](https://github.com/ben-ranford/cellin/commit/360c64c5ac87ee4006c4433a22255ed8d6da7103))
* **storage:** add mongodb and redis backends ([#91](https://github.com/ben-ranford/cellin/issues/91)) ([a91aa4c](https://github.com/ben-ranford/cellin/commit/a91aa4ce85a9f7d81b4b007b036c7d05f063d05c))
* **storage:** add role-specific storage bundle config ([#87](https://github.com/ben-ranford/cellin/issues/87)) ([1a0a028](https://github.com/ben-ranford/cellin/commit/1a0a028b7c45beb0fb1bffc6385242d36020f2b4))
* **storage:** default init to in-memory preset ([#88](https://github.com/ben-ranford/cellin/issues/88)) ([59f69bb](https://github.com/ben-ranford/cellin/commit/59f69bb28aa9983513a6e9b277bc0c37922758e4))


### Bug Fixes

* address sonar store issues ([#123](https://github.com/ben-ranford/cellin/issues/123)) ([888aa4c](https://github.com/ben-ranford/cellin/commit/888aa4c9ced0d2abd6fea8bc0d63fa3fce9db08b))
* **cli:** avoid flagged storage config write helper ([#130](https://github.com/ben-ranford/cellin/issues/130)) ([94b84ee](https://github.com/ben-ranford/cellin/commit/94b84ee6de5d40315de4ab0aa45b972cd42dcc81))
* correct one-pass dreaming strategy bugs ([#140](https://github.com/ben-ranford/cellin/issues/140)) ([3fded69](https://github.com/ben-ranford/cellin/commit/3fded6943af799d4fcc238c6e80c388624170993))
* **dreaming:** remove redundant dedup list call ([#129](https://github.com/ben-ranford/cellin/issues/129)) ([b12a7c9](https://github.com/ben-ranford/cellin/commit/b12a7c9a081736947503951442165add4090877f))
* guard eval and release flows against empty outputs ([#144](https://github.com/ben-ranford/cellin/issues/144)) ([3c04b3b](https://github.com/ben-ranford/cellin/commit/3c04b3b12486adb82ba7831a2a540de9b5ef5669))
* harden runtime storage validation and reporting ([#141](https://github.com/ben-ranford/cellin/issues/141)) ([cb92543](https://github.com/ben-ranford/cellin/commit/cb92543e9435846f6d953e992c12463e1b5a8050))
* **release:** align release-please tag config ([#67](https://github.com/ben-ranford/cellin/issues/67)) ([fc09eb2](https://github.com/ben-ranford/cellin/commit/fc09eb2d1646e95ca1b1655cdde5310ec6abd335))
* **release:** fetch full history for previews ([#84](https://github.com/ben-ranford/cellin/issues/84)) ([91c062e](https://github.com/ben-ranford/cellin/commit/91c062e0f06a5229d6729675876be4a2aa1ccdd4))
* **release:** ignore prerelease tags in preview base ([#86](https://github.com/ben-ranford/cellin/issues/86)) ([135a4cb](https://github.com/ben-ranford/cellin/commit/135a4cb2e2f593ff32c24e6ce98aad89e8ded6ab))
* **release:** label release prs ([#69](https://github.com/ben-ranford/cellin/issues/69)) ([1a2b360](https://github.com/ben-ranford/cellin/commit/1a2b360222a8bbf70c98363ab3f33545e038f1dc))
* **release:** refresh preview metadata after version stamp ([#83](https://github.com/ben-ranford/cellin/issues/83)) ([ddf0b09](https://github.com/ben-ranford/cellin/commit/ddf0b09c589b0614be98ae01c5c0446bf373b2f3))
* **sonar:** harden test fixtures and credential-like literals ([#95](https://github.com/ben-ranford/cellin/issues/95) [#96](https://github.com/ben-ranford/cellin/issues/96) [#109](https://github.com/ben-ranford/cellin/issues/109)) ([#125](https://github.com/ben-ranford/cellin/issues/125)) ([b7851f1](https://github.com/ben-ranford/cellin/commit/b7851f155595057e42460d37ffd662517443d9f6))
* **sonar:** resolve remote vector backend test issues ([#100](https://github.com/ben-ranford/cellin/issues/100)-[#107](https://github.com/ben-ranford/cellin/issues/107)) ([#126](https://github.com/ben-ranford/cellin/issues/126)) ([eb6d4e5](https://github.com/ben-ranford/cellin/commit/eb6d4e55e1160ae89fc88a4a71ad900def9475b3))
* **sonar:** resolve retrieval test placeholder issues ([#111](https://github.com/ben-ranford/cellin/issues/111) [#112](https://github.com/ben-ranford/cellin/issues/112)) ([#122](https://github.com/ben-ranford/cellin/issues/122)) ([7e8efd2](https://github.com/ben-ranford/cellin/commit/7e8efd266e5d5194ce653d279165e00088e29208))
* use collision-safe edge identifiers for sqlite graphs ([#142](https://github.com/ben-ranford/cellin/issues/142)) ([fdb6ec6](https://github.com/ben-ranford/cellin/commit/fdb6ec65982f6822a2f6c1a1d2bfca934e142e04))


### Documentation

* add fallback lefthook install command ([#131](https://github.com/ben-ranford/cellin/issues/131)) ([f7d486a](https://github.com/ben-ranford/cellin/commit/f7d486a100efd317df297db13b05c44a6b57a25b))
* **contributing:** explain release-please changelog inputs ([#71](https://github.com/ben-ranford/cellin/issues/71)) ([37eecdf](https://github.com/ben-ranford/cellin/commit/37eecdfdac2ed6ef3d10f3b5daac6ea139e803e0))
* **readme:** show release status badge ([#70](https://github.com/ben-ranford/cellin/issues/70)) ([46c82e4](https://github.com/ben-ranford/cellin/commit/46c82e41181bfd5e88c6326a404e8c1395757a38))

## [0.2.0](https://github.com/ben-ranford/cellin/compare/cellin-v0.1.1...cellin-v0.2.0) (2026-04-05)


### Features

* **ingest:** add multimodal ingestion and local stores ([#15](https://github.com/ben-ranford/cellin/issues/15)) ([671e0ae](https://github.com/ben-ranford/cellin/commit/671e0aeda51cfd5df9a30bc9fa4c185a24c1958f))


### Bug Fixes

* **cli:** respect zero trace limit ([#51](https://github.com/ben-ranford/cellin/issues/51)) ([e1e1e10](https://github.com/ben-ranford/cellin/commit/e1e1e10bff06309c64e8ea2fb02b91a09f43bc89))
* **dreaming:** align abstraction token counts ([#49](https://github.com/ben-ranford/cellin/issues/49)) ([9d6c39e](https://github.com/ben-ranford/cellin/commit/9d6c39e6e861f25700add2046db6a2ae1f979af1))
* **evals:** relax float comparisons ([#53](https://github.com/ben-ranford/cellin/issues/53)) ([#60](https://github.com/ben-ranford/cellin/issues/60)) ([4c90a35](https://github.com/ben-ranford/cellin/commit/4c90a3510c065b68368e72ded1ffab6e87dfd558))
* **release:** harden rolling release inputs ([#52](https://github.com/ben-ranford/cellin/issues/52)) ([#59](https://github.com/ben-ranford/cellin/issues/59)) ([fd3bf65](https://github.com/ben-ranford/cellin/commit/fd3bf65cc093d4fd23a9d7f16fcc4de9f7c7845e))


### Documentation

* **readme:** add release badges ([#47](https://github.com/ben-ranford/cellin/issues/47)) ([12ee8cb](https://github.com/ben-ranford/cellin/commit/12ee8cb99631fb2c79243125797d53f123bf1af9))
* **readme:** link PyPI install ([#48](https://github.com/ben-ranford/cellin/issues/48)) ([54e83c6](https://github.com/ben-ranford/cellin/commit/54e83c608a01bd0fda6255dcecb549c6cb60d02b))

## [0.1.1] - 2026-04-05

### Bootstrap

- Established the public library release surface and automated stable release baseline for future release-please-managed cuts.
