globalThis.__nitro_main__ = import.meta.url;
import { i as HTTPError, n as defineLazyEventHandler, t as H3Core } from "./_libs/h3+rou3+srvx.mjs";
import { t as HookableCore } from "./_libs/hookable.mjs";
import { r as FastResponse } from "./_libs/h3-v2+rou3+srvx.mjs";
//#region #nitro-vite-setup
function lazyService(loader) {
	let promise, mod;
	return { fetch(req) {
		if (mod) return mod.fetch(req);
		if (!promise) promise = loader().then((_mod) => mod = _mod.default || _mod);
		return promise.then((mod) => mod.fetch(req));
	} };
}
var services = { ["ssr"]: lazyService(() => import("./_ssr/ssr.mjs")) };
globalThis.__nitro_vite_envs__ = services;
//#endregion
//#region #nitro/virtual/public-assets-data
var public_assets_data_default = {
	"/assets/index-BQI7sK49.js": {
		"type": "text/javascript; charset=utf-8",
		"etag": "\"5a423-Aca4ztfm+7R4hcZy9ni0l0qgLYk\"",
		"mtime": "2026-10-31T11:19:50.306Z",
		"size": 369699,
		"path": "../public/assets/index-BQI7sK49.js"
	},
	"/robots.txt": {
		"type": "text/plain; charset=utf-8",
		"etag": "\"a0-CKGXSIe7TSsqDTmGm/nY1t/o5d0\"",
		"mtime": "2026-10-30T07:22:13.977Z",
		"size": 160,
		"path": "../public/robots.txt"
	},
	"/assets/inter-cyrillic-400-normal-obahsSVq.woff2": {
		"type": "font/woff2",
		"etag": "\"1e20-2UATdNvSyhAwBTFW7JWXRnJeZyk\"",
		"mtime": "2026-10-31T11:19:50.316Z",
		"size": 7712,
		"path": "../public/assets/inter-cyrillic-400-normal-obahsSVq.woff2"
	},
	"/assets/inter-cyrillic-400-normal-HOLc17fK.woff": {
		"type": "font/woff",
		"etag": "\"2634-ivoNz55T3CYjsRGYVvI78V6Hg84\"",
		"mtime": "2026-10-31T11:19:50.314Z",
		"size": 9780,
		"path": "../public/assets/inter-cyrillic-400-normal-HOLc17fK.woff"
	},
	"/assets/inter-cyrillic-500-normal-BasfLYem.woff2": {
		"type": "font/woff2",
		"etag": "\"1edc-4p+L4DlZmQVqry+RH9lMmJQ+P0U\"",
		"mtime": "2026-10-31T11:19:50.318Z",
		"size": 7900,
		"path": "../public/assets/inter-cyrillic-500-normal-BasfLYem.woff2"
	},
	"/assets/inter-cyrillic-600-normal-4D_pXhcN.woff": {
		"type": "font/woff",
		"etag": "\"26d0-I2CCKTFIJy7UNImTmVTFMc8WGWM\"",
		"mtime": "2026-10-31T11:19:50.322Z",
		"size": 9936,
		"path": "../public/assets/inter-cyrillic-600-normal-4D_pXhcN.woff"
	},
	"/assets/inter-cyrillic-500-normal-CxZf_p3X.woff": {
		"type": "font/woff",
		"etag": "\"26d4-lAKYDJFVYDMKcLY/oR+ZyfOsllA\"",
		"mtime": "2026-10-31T11:19:50.322Z",
		"size": 9940,
		"path": "../public/assets/inter-cyrillic-500-normal-CxZf_p3X.woff"
	},
	"/assets/inter-cyrillic-600-normal-CWCymEST.woff2": {
		"type": "font/woff2",
		"etag": "\"1f24-tca4CMW+seK3RqmUMU0o0VZmyqg\"",
		"mtime": "2026-10-31T11:19:50.322Z",
		"size": 7972,
		"path": "../public/assets/inter-cyrillic-600-normal-CWCymEST.woff2"
	},
	"/assets/inter-cyrillic-700-normal-CjBOestx.woff2": {
		"type": "font/woff2",
		"etag": "\"1ee0-D8f9uATzhIzndMrJ0Y11iQjPdds\"",
		"mtime": "2026-10-31T11:19:50.322Z",
		"size": 7904,
		"path": "../public/assets/inter-cyrillic-700-normal-CjBOestx.woff2"
	},
	"/assets/inter-cyrillic-700-normal-DrXBdSj3.woff": {
		"type": "font/woff",
		"etag": "\"26b8-AaxySEnVJ+M+6514gHrK4csJma0\"",
		"mtime": "2026-10-31T11:19:50.332Z",
		"size": 9912,
		"path": "../public/assets/inter-cyrillic-700-normal-DrXBdSj3.woff"
	},
	"/assets/inter-cyrillic-800-normal-CCHyn08d.woff": {
		"type": "font/woff",
		"etag": "\"26d8-ceFGxv32FiqqsGar8DD9nSG6UNU\"",
		"mtime": "2026-10-31T11:19:50.336Z",
		"size": 9944,
		"path": "../public/assets/inter-cyrillic-800-normal-CCHyn08d.woff"
	},
	"/favicon.ico": {
		"type": "image/vnd.microsoft.icon",
		"etag": "\"4f95-3RXc3p2mhEAs1WBwaIvE0Y0uu0Y\"",
		"mtime": "2026-10-30T07:22:13.918Z",
		"size": 20373,
		"path": "../public/favicon.ico"
	},
	"/assets/inter-cyrillic-800-normal-C7MGvYyJ.woff2": {
		"type": "font/woff2",
		"etag": "\"1f38-tRR9TLwT+T/ihFvufr8MmHh/uwU\"",
		"mtime": "2026-10-31T11:19:50.332Z",
		"size": 7992,
		"path": "../public/assets/inter-cyrillic-800-normal-C7MGvYyJ.woff2"
	},
	"/assets/inter-cyrillic-ext-400-normal-DQukG94-.woff": {
		"type": "font/woff",
		"etag": "\"3418-0efK3fiFhInlHHjq0SFm+GVey2Y\"",
		"mtime": "2026-10-31T11:19:50.344Z",
		"size": 13336,
		"path": "../public/assets/inter-cyrillic-ext-400-normal-DQukG94-.woff"
	},
	"/assets/inter-cyrillic-ext-500-normal-BmqWE9Dz.woff": {
		"type": "font/woff",
		"etag": "\"348c-1TbeWRwD3bVotPqIc3c/7sVxfo0\"",
		"mtime": "2026-10-31T11:19:50.349Z",
		"size": 13452,
		"path": "../public/assets/inter-cyrillic-ext-500-normal-BmqWE9Dz.woff"
	},
	"/assets/inter-cyrillic-ext-500-normal-B0yAr1jD.woff2": {
		"type": "font/woff2",
		"etag": "\"28c0-a4jJ9g181ZteaPVR7IOs0hVwtQg\"",
		"mtime": "2026-10-31T11:19:50.347Z",
		"size": 10432,
		"path": "../public/assets/inter-cyrillic-ext-500-normal-B0yAr1jD.woff2"
	},
	"/assets/inter-cyrillic-ext-600-normal-Bcila6Z-.woff": {
		"type": "font/woff",
		"etag": "\"3498-zNJjP5Amk16bEdqbbZNObDtX308\"",
		"mtime": "2026-10-31T11:19:50.352Z",
		"size": 13464,
		"path": "../public/assets/inter-cyrillic-ext-600-normal-Bcila6Z-.woff"
	},
	"/assets/inter-cyrillic-ext-400-normal-BQZuk6qB.woff2": {
		"type": "font/woff2",
		"etag": "\"27f8-vx2gCiZcZIS7BSyHWqEe1Lm5p8Y\"",
		"mtime": "2026-10-31T11:19:50.342Z",
		"size": 10232,
		"path": "../public/assets/inter-cyrillic-ext-400-normal-BQZuk6qB.woff2"
	},
	"/assets/inter-cyrillic-ext-700-normal-BjwYoWNd.woff2": {
		"type": "font/woff2",
		"etag": "\"2900-0N8FIokKpqZhWi+D5DLndc4iUGY\"",
		"mtime": "2026-10-31T11:19:50.358Z",
		"size": 10496,
		"path": "../public/assets/inter-cyrillic-ext-700-normal-BjwYoWNd.woff2"
	},
	"/assets/inter-cyrillic-ext-700-normal-LO58E6JB.woff": {
		"type": "font/woff",
		"etag": "\"3460-O0B5vyXV2ljXcmbQhvmTQJXWVuc\"",
		"mtime": "2026-10-31T11:19:50.358Z",
		"size": 13408,
		"path": "../public/assets/inter-cyrillic-ext-700-normal-LO58E6JB.woff"
	},
	"/assets/inter-cyrillic-ext-600-normal-Dfes3d0z.woff2": {
		"type": "font/woff2",
		"etag": "\"28f4-KdWYNIoSwUf7MLulzakpM8nepFc\"",
		"mtime": "2026-10-31T11:19:50.354Z",
		"size": 10484,
		"path": "../public/assets/inter-cyrillic-ext-600-normal-Dfes3d0z.woff2"
	},
	"/assets/inter-cyrillic-ext-800-normal-BZOjs1Xv.woff2": {
		"type": "font/woff2",
		"etag": "\"28c8-pp494C0rYU+y/vvB/vL/Z3Tf5QM\"",
		"mtime": "2026-10-31T11:19:50.358Z",
		"size": 10440,
		"path": "../public/assets/inter-cyrillic-ext-800-normal-BZOjs1Xv.woff2"
	},
	"/assets/inter-cyrillic-ext-800-normal-Ca-gJeZY.woff": {
		"type": "font/woff",
		"etag": "\"34a4-tRNRDYiDrkvIXJlq9ukGfy3Pe4s\"",
		"mtime": "2026-10-31T11:19:50.364Z",
		"size": 13476,
		"path": "../public/assets/inter-cyrillic-ext-800-normal-Ca-gJeZY.woff"
	},
	"/assets/inter-greek-400-normal-q2sYcFCs.woff": {
		"type": "font/woff",
		"etag": "\"26c4-bdX1N3nNMZxQdZJFiVUIvfgvPUk\"",
		"mtime": "2026-10-31T11:19:50.368Z",
		"size": 9924,
		"path": "../public/assets/inter-greek-400-normal-q2sYcFCs.woff"
	},
	"/assets/inter-greek-500-normal-BIZE56-Y.woff2": {
		"type": "font/woff2",
		"etag": "\"1ef0-rzB1Hth7JnUPaEXqA8yr0SpwMxk\"",
		"mtime": "2026-10-31T11:19:50.373Z",
		"size": 7920,
		"path": "../public/assets/inter-greek-500-normal-BIZE56-Y.woff2"
	},
	"/assets/inter-greek-500-normal-Xzm54t5V.woff": {
		"type": "font/woff",
		"etag": "\"26fc-aBzOXUzctfu1t0AWou6edVMARPA\"",
		"mtime": "2026-10-31T11:19:50.379Z",
		"size": 9980,
		"path": "../public/assets/inter-greek-500-normal-Xzm54t5V.woff"
	},
	"/assets/inter-greek-400-normal-B4URO6DV.woff2": {
		"type": "font/woff2",
		"etag": "\"1e60-ha06h5lB7nxuWvNKf61Dcnc1d1I\"",
		"mtime": "2026-10-31T11:19:50.368Z",
		"size": 7776,
		"path": "../public/assets/inter-greek-400-normal-B4URO6DV.woff2"
	},
	"/assets/inter-greek-600-normal-BZpKdvQh.woff": {
		"type": "font/woff",
		"etag": "\"2730-u0VEy1HjIfUMvAeVgiAlRXW3Gg0\"",
		"mtime": "2026-10-31T11:19:50.383Z",
		"size": 10032,
		"path": "../public/assets/inter-greek-600-normal-BZpKdvQh.woff"
	},
	"/assets/inter-greek-600-normal-plRanbMR.woff2": {
		"type": "font/woff2",
		"etag": "\"1f08-dL8q9T10oywr5Ie+w0fBRkD/K6s\"",
		"mtime": "2026-10-31T11:19:50.391Z",
		"size": 7944,
		"path": "../public/assets/inter-greek-600-normal-plRanbMR.woff2"
	},
	"/assets/inter-greek-700-normal-C3JjAnD8.woff2": {
		"type": "font/woff2",
		"etag": "\"1ef0-LHrivJw+k04PRvScx047LwlyCQM\"",
		"mtime": "2026-10-31T11:19:50.399Z",
		"size": 7920,
		"path": "../public/assets/inter-greek-700-normal-C3JjAnD8.woff2"
	},
	"/assets/inter-greek-800-normal-CLIouy3y.woff2": {
		"type": "font/woff2",
		"etag": "\"1ed4-u4yriOaShZ5ugDro6YOGHdOtRCE\"",
		"mtime": "2026-10-31T11:19:50.399Z",
		"size": 7892,
		"path": "../public/assets/inter-greek-800-normal-CLIouy3y.woff2"
	},
	"/assets/inter-greek-700-normal-BUv2fZ6O.woff": {
		"type": "font/woff",
		"etag": "\"26fc-6VHcgzrZm5Dq3Ofg/SG0LimdBHI\"",
		"mtime": "2026-10-31T11:19:50.395Z",
		"size": 9980,
		"path": "../public/assets/inter-greek-700-normal-BUv2fZ6O.woff"
	},
	"/assets/inter-greek-800-normal-BU00tryP.woff": {
		"type": "font/woff",
		"etag": "\"26ec-eSjDFedJANOoY08QW7AQWExRW0M\"",
		"mtime": "2026-10-31T11:19:50.399Z",
		"size": 9964,
		"path": "../public/assets/inter-greek-800-normal-BU00tryP.woff"
	},
	"/assets/inter-greek-ext-400-normal-KugGGMne.woff": {
		"type": "font/woff",
		"etag": "\"1b98-M0BooO/fFnrQlgRJzUMnDMWQ/Qo\"",
		"mtime": "2026-10-31T11:19:50.411Z",
		"size": 7064,
		"path": "../public/assets/inter-greek-ext-400-normal-KugGGMne.woff"
	},
	"/assets/inter-greek-ext-400-normal-DGGRlc-M.woff2": {
		"type": "font/woff2",
		"etag": "\"1490-FueWPOzdNQpScjKjfRcVv5Yv1HM\"",
		"mtime": "2026-10-31T11:19:50.408Z",
		"size": 5264,
		"path": "../public/assets/inter-greek-ext-400-normal-DGGRlc-M.woff2"
	},
	"/assets/inter-greek-ext-500-normal-2j5mBUwD.woff": {
		"type": "font/woff",
		"etag": "\"1c18-qcQk7wkL8ZD2jgfjekhd8K3qWn0\"",
		"mtime": "2026-10-31T11:19:50.414Z",
		"size": 7192,
		"path": "../public/assets/inter-greek-ext-500-normal-2j5mBUwD.woff"
	},
	"/assets/inter-greek-ext-500-normal-C4iEst2y.woff2": {
		"type": "font/woff2",
		"etag": "\"1534-eUg1Jo5WjHY2xgQTOkilC7LKn3I\"",
		"mtime": "2026-10-31T11:19:50.416Z",
		"size": 5428,
		"path": "../public/assets/inter-greek-ext-500-normal-C4iEst2y.woff2"
	},
	"/assets/inter-greek-ext-600-normal-B8X0CLgF.woff": {
		"type": "font/woff",
		"etag": "\"1c2c-ceWCifetUVyF5uPKYdA318gl/j8\"",
		"mtime": "2026-10-31T11:19:50.418Z",
		"size": 7212,
		"path": "../public/assets/inter-greek-ext-600-normal-B8X0CLgF.woff"
	},
	"/assets/inter-greek-ext-600-normal-DRtmH8MT.woff2": {
		"type": "font/woff2",
		"etag": "\"1538-GoE9+rMXdldLs0MUbnyI6GfidCU\"",
		"mtime": "2026-10-31T11:19:50.418Z",
		"size": 5432,
		"path": "../public/assets/inter-greek-ext-600-normal-DRtmH8MT.woff2"
	},
	"/assets/inter-greek-ext-700-normal-qfdV9bQt.woff2": {
		"type": "font/woff2",
		"etag": "\"1544-Po0VSwP0X4mCd4Bi+vzYGFAlRtE\"",
		"mtime": "2026-10-31T11:19:50.418Z",
		"size": 5444,
		"path": "../public/assets/inter-greek-ext-700-normal-qfdV9bQt.woff2"
	},
	"/assets/inter-greek-ext-700-normal-BoQ6DsYi.woff": {
		"type": "font/woff",
		"etag": "\"1c30-9rBd06jWL1DufBIVe/ZeKo67yXU\"",
		"mtime": "2026-10-31T11:19:50.418Z",
		"size": 7216,
		"path": "../public/assets/inter-greek-ext-700-normal-BoQ6DsYi.woff"
	},
	"/assets/inter-latin-400-normal-CyCys3Eg.woff": {
		"type": "font/woff",
		"etag": "\"77e8-SbvLwKxssThdk7eEO6Aafq1EDIA\"",
		"mtime": "2026-10-31T11:19:50.449Z",
		"size": 30696,
		"path": "../public/assets/inter-latin-400-normal-CyCys3Eg.woff"
	},
	"/assets/inter-greek-ext-800-normal-DUe57HfS.woff": {
		"type": "font/woff",
		"etag": "\"1c24-LjrG/6CQQ4ta5ur/PHJMpQ7KQzg\"",
		"mtime": "2026-10-31T11:19:50.441Z",
		"size": 7204,
		"path": "../public/assets/inter-greek-ext-800-normal-DUe57HfS.woff"
	},
	"/assets/inter-greek-ext-800-normal-B--PVpEC.woff2": {
		"type": "font/woff2",
		"etag": "\"15ac-Q1GctRDY5Zz/MVQWmhZRBXW9nhg\"",
		"mtime": "2026-10-31T11:19:50.434Z",
		"size": 5548,
		"path": "../public/assets/inter-greek-ext-800-normal-B--PVpEC.woff2"
	},
	"/assets/inter-latin-400-normal-C38fXH4l.woff2": {
		"type": "font/woff2",
		"etag": "\"5c70-aPZFxrb/EuJcVLE9TtEZ5jHcuyY\"",
		"mtime": "2026-10-31T11:19:50.441Z",
		"size": 23664,
		"path": "../public/assets/inter-latin-400-normal-C38fXH4l.woff2"
	},
	"/assets/inter-latin-500-normal-BL9OpVg8.woff": {
		"type": "font/woff",
		"etag": "\"7a34-RiJoWDij89wbmUrQ9vApTdR9iMs\"",
		"mtime": "2026-10-31T11:19:50.452Z",
		"size": 31284,
		"path": "../public/assets/inter-latin-500-normal-BL9OpVg8.woff"
	},
	"/assets/inter-latin-600-normal-CiBQ2DWP.woff": {
		"type": "font/woff",
		"etag": "\"7a1c-7yTNkhBBRpiqSdmpUeo8hP6GAv8\"",
		"mtime": "2026-10-31T11:19:50.461Z",
		"size": 31260,
		"path": "../public/assets/inter-latin-600-normal-CiBQ2DWP.woff"
	},
	"/assets/inter-latin-500-normal-Cerq10X2.woff2": {
		"type": "font/woff2",
		"etag": "\"5ed0-a2bHQb+Lw84kivBLIFGmSKODkdY\"",
		"mtime": "2026-10-31T11:19:50.454Z",
		"size": 24272,
		"path": "../public/assets/inter-latin-500-normal-Cerq10X2.woff2"
	},
	"/assets/inter-latin-600-normal-LgqL8muc.woff2": {
		"type": "font/woff2",
		"etag": "\"5f84-4NYfbcUR1koHKy9NyU4VXs8btvY\"",
		"mtime": "2026-10-31T11:19:50.468Z",
		"size": 24452,
		"path": "../public/assets/inter-latin-600-normal-LgqL8muc.woff2"
	},
	"/assets/inter-latin-700-normal-BLAVimhd.woff": {
		"type": "font/woff",
		"etag": "\"7a58-cQvU1F9kXU/ZpvVIy7T98mV4J+E\"",
		"mtime": "2026-10-31T11:19:50.469Z",
		"size": 31320,
		"path": "../public/assets/inter-latin-700-normal-BLAVimhd.woff"
	},
	"/assets/inter-latin-800-normal-BYj_oED-.woff2": {
		"type": "font/woff2",
		"etag": "\"5f50-IH7F4V9VLmEQwxM+y33NeDbUL/4\"",
		"mtime": "2026-10-31T11:19:50.473Z",
		"size": 24400,
		"path": "../public/assets/inter-latin-800-normal-BYj_oED-.woff2"
	},
	"/assets/inter-latin-700-normal-Yt3aPRUw.woff2": {
		"type": "font/woff2",
		"etag": "\"5f24-UZenrrIkVBEKofPvPtTJjKfvG6E\"",
		"mtime": "2026-10-31T11:19:50.473Z",
		"size": 24356,
		"path": "../public/assets/inter-latin-700-normal-Yt3aPRUw.woff2"
	},
	"/assets/inter-latin-ext-400-normal-C1nco2VV.woff2": {
		"type": "font/woff2",
		"etag": "\"88b8-G/H4NxekwCldh2+r75P8W7SzF98\"",
		"mtime": "2026-10-31T11:19:50.491Z",
		"size": 35e3,
		"path": "../public/assets/inter-latin-ext-400-normal-C1nco2VV.woff2"
	},
	"/assets/inter-latin-ext-400-normal-77YHD8bZ.woff": {
		"type": "font/woff",
		"etag": "\"b9c8-Bhja6T6VCwLwb1wadgBSy3MfJBM\"",
		"mtime": "2026-10-31T11:19:50.473Z",
		"size": 47560,
		"path": "../public/assets/inter-latin-ext-400-normal-77YHD8bZ.woff"
	},
	"/assets/inter-latin-ext-500-normal-BxGbmqWO.woff": {
		"type": "font/woff",
		"etag": "\"bd6c-QCyyMz9w4NbwgJiEMxZozI/r+Ds\"",
		"mtime": "2026-10-31T11:19:50.493Z",
		"size": 48492,
		"path": "../public/assets/inter-latin-ext-500-normal-BxGbmqWO.woff"
	},
	"/assets/inter-latin-800-normal-D1mf63XC.woff": {
		"type": "font/woff",
		"etag": "\"7a40-UpFX9MdirTjPCGZHRtLiDecFf2M\"",
		"mtime": "2026-10-31T11:19:50.473Z",
		"size": 31296,
		"path": "../public/assets/inter-latin-800-normal-D1mf63XC.woff"
	},
	"/assets/inter-latin-ext-500-normal-CV4jyFjo.woff2": {
		"type": "font/woff2",
		"etag": "\"8cb8-ncqRX/i2leXjDT1PI3s6qVpmf6g\"",
		"mtime": "2026-10-31T11:19:50.496Z",
		"size": 36024,
		"path": "../public/assets/inter-latin-ext-500-normal-CV4jyFjo.woff2"
	},
	"/assets/inter-latin-ext-600-normal-D2bJ5OIk.woff2": {
		"type": "font/woff2",
		"etag": "\"8da4-7QGAEIYrxx26VfuVX2p4gRkHOKo\"",
		"mtime": "2026-10-31T11:19:50.498Z",
		"size": 36260,
		"path": "../public/assets/inter-latin-ext-600-normal-D2bJ5OIk.woff2"
	},
	"/assets/inter-latin-ext-600-normal-CIVaiw4L.woff": {
		"type": "font/woff",
		"etag": "\"be1c-8cD1HFH6FU9hlLytWwPGGUY70n4\"",
		"mtime": "2026-10-31T11:19:50.498Z",
		"size": 48668,
		"path": "../public/assets/inter-latin-ext-600-normal-CIVaiw4L.woff"
	},
	"/assets/inter-latin-ext-700-normal-Ca8adRJv.woff2": {
		"type": "font/woff2",
		"etag": "\"8d94-yNVVBni5SnCMi1iBd7oIoQ4VttA\"",
		"mtime": "2026-10-31T11:19:50.498Z",
		"size": 36244,
		"path": "../public/assets/inter-latin-ext-700-normal-Ca8adRJv.woff2"
	},
	"/assets/inter-latin-ext-700-normal-TidjK2hL.woff": {
		"type": "font/woff",
		"etag": "\"bdf8-cQlr/tU/y6KwF0S0VxtHZkfIWHg\"",
		"mtime": "2026-10-31T11:19:50.508Z",
		"size": 48632,
		"path": "../public/assets/inter-latin-ext-700-normal-TidjK2hL.woff"
	},
	"/assets/inter-latin-ext-800-normal-BOMpwxm3.woff": {
		"type": "font/woff",
		"etag": "\"bdd0-e9JtltwUhu4lhLtF32/MDciAmCY\"",
		"mtime": "2026-10-31T11:19:50.511Z",
		"size": 48592,
		"path": "../public/assets/inter-latin-ext-800-normal-BOMpwxm3.woff"
	},
	"/assets/inter-latin-ext-800-normal-DZJjya6U.woff2": {
		"type": "font/woff2",
		"etag": "\"8d20-a9fRYLOE2E0Dc7x6te5NBhmCEzs\"",
		"mtime": "2026-10-31T11:19:50.511Z",
		"size": 36128,
		"path": "../public/assets/inter-latin-ext-800-normal-DZJjya6U.woff2"
	},
	"/assets/inter-vietnamese-500-normal-DOriooB6.woff2": {
		"type": "font/woff2",
		"etag": "\"13f8-CUM23jWJKM6nB7lsyh1fHy5MoZ4\"",
		"mtime": "2026-10-31T11:19:50.522Z",
		"size": 5112,
		"path": "../public/assets/inter-vietnamese-500-normal-DOriooB6.woff2"
	},
	"/assets/inter-vietnamese-400-normal-DMkecbls.woff2": {
		"type": "font/woff2",
		"etag": "\"136c-x5LSIOvtcMpNpAaXtHsgRr9Y068\"",
		"mtime": "2026-10-31T11:19:50.520Z",
		"size": 4972,
		"path": "../public/assets/inter-vietnamese-400-normal-DMkecbls.woff2"
	},
	"/assets/inter-vietnamese-500-normal-mJboJaSs.woff": {
		"type": "font/woff",
		"etag": "\"19c4-GIi0pWixVrurGnEPzcWNPRmQHPA\"",
		"mtime": "2026-10-31T11:19:50.526Z",
		"size": 6596,
		"path": "../public/assets/inter-vietnamese-500-normal-mJboJaSs.woff"
	},
	"/assets/inter-vietnamese-600-normal-BuLX-rYi.woff": {
		"type": "font/woff",
		"etag": "\"19f0-dZ/EhN2gqjVMAOO8T5PiEnOw62w\"",
		"mtime": "2026-10-31T11:19:50.528Z",
		"size": 6640,
		"path": "../public/assets/inter-vietnamese-600-normal-BuLX-rYi.woff"
	},
	"/assets/inter-vietnamese-400-normal-Bbgyi5SW.woff": {
		"type": "font/woff",
		"etag": "\"1964-Uz2qf+4P37GRYrj2tnfiNdz3cwc\"",
		"mtime": "2026-10-31T11:19:50.518Z",
		"size": 6500,
		"path": "../public/assets/inter-vietnamese-400-normal-Bbgyi5SW.woff"
	},
	"/assets/inter-vietnamese-700-normal-BZaoP0fm.woff": {
		"type": "font/woff",
		"etag": "\"19e8-bdSpfj6ZS6+Lvz7ijFjLexeYSQ4\"",
		"mtime": "2026-10-31T11:19:50.532Z",
		"size": 6632,
		"path": "../public/assets/inter-vietnamese-700-normal-BZaoP0fm.woff"
	},
	"/assets/inter-vietnamese-600-normal-Cc8MFFhd.woff2": {
		"type": "font/woff2",
		"etag": "\"13ec-+Z5aj32FhioUUaW+56MD6v89VjU\"",
		"mtime": "2026-10-31T11:19:50.532Z",
		"size": 5100,
		"path": "../public/assets/inter-vietnamese-600-normal-Cc8MFFhd.woff2"
	},
	"/assets/inter-vietnamese-700-normal-DlLaEgI2.woff2": {
		"type": "font/woff2",
		"etag": "\"13f0-2+yadyA0heA/Lel/M8LdWlzEV1U\"",
		"mtime": "2026-10-31T11:19:50.536Z",
		"size": 5104,
		"path": "../public/assets/inter-vietnamese-700-normal-DlLaEgI2.woff2"
	},
	"/assets/inter-vietnamese-800-normal-DDlpr_Ee.woff": {
		"type": "font/woff",
		"etag": "\"19f4-7Ao4j773lVBkMRNUAGG1W8n0Wpg\"",
		"mtime": "2026-10-31T11:19:50.540Z",
		"size": 6644,
		"path": "../public/assets/inter-vietnamese-800-normal-DDlpr_Ee.woff"
	},
	"/assets/noto-sans-devanagari-devanagari-400-normal-BlDd6KY1.woff2": {
		"type": "font/woff2",
		"etag": "\"c4f0-shS1JX+C+E1zYghSmcQcwlQc0xI\"",
		"mtime": "2026-10-31T11:19:50.544Z",
		"size": 50416,
		"path": "../public/assets/noto-sans-devanagari-devanagari-400-normal-BlDd6KY1.woff2"
	},
	"/assets/noto-sans-devanagari-devanagari-500-normal-DO6LFp12.woff": {
		"type": "font/woff",
		"etag": "\"11738-+lOloC4Zh5gsMHRf6JCK4mCKloA\"",
		"mtime": "2026-10-31T11:19:50.550Z",
		"size": 71480,
		"path": "../public/assets/noto-sans-devanagari-devanagari-500-normal-DO6LFp12.woff"
	},
	"/assets/noto-sans-devanagari-devanagari-400-normal-CdOJmQ4E.woff": {
		"type": "font/woff",
		"etag": "\"10b74-Yr7kLl9xQWaXE2m5WwDmdbqZJgI\"",
		"mtime": "2026-10-31T11:19:50.548Z",
		"size": 68468,
		"path": "../public/assets/noto-sans-devanagari-devanagari-400-normal-CdOJmQ4E.woff"
	},
	"/assets/noto-sans-devanagari-devanagari-500-normal-DVtwyDnM.woff2": {
		"type": "font/woff2",
		"etag": "\"d174-eQtH4P0m1AfaRtYyq813nz3frSU\"",
		"mtime": "2026-10-31T11:19:50.553Z",
		"size": 53620,
		"path": "../public/assets/noto-sans-devanagari-devanagari-500-normal-DVtwyDnM.woff2"
	},
	"/assets/noto-sans-devanagari-devanagari-600-normal-B5tDaqnD.woff": {
		"type": "font/woff",
		"etag": "\"117f4-l6DROMqtliSSOBCd4np6nm/4vGk\"",
		"mtime": "2026-10-31T11:19:50.556Z",
		"size": 71668,
		"path": "../public/assets/noto-sans-devanagari-devanagari-600-normal-B5tDaqnD.woff"
	},
	"/assets/inter-vietnamese-800-normal-Cm7tD1pz.woff2": {
		"type": "font/woff2",
		"etag": "\"1438-sW9norLbyZBBY2h8IMAsOcEqu1s\"",
		"mtime": "2026-10-31T11:19:50.540Z",
		"size": 5176,
		"path": "../public/assets/inter-vietnamese-800-normal-Cm7tD1pz.woff2"
	},
	"/assets/noto-sans-devanagari-devanagari-600-normal-BeyktMLo.woff2": {
		"type": "font/woff2",
		"etag": "\"d1d4-fjTopLkpU/CGSHs34W+c7tVg5fk\"",
		"mtime": "2026-10-31T11:19:50.559Z",
		"size": 53716,
		"path": "../public/assets/noto-sans-devanagari-devanagari-600-normal-BeyktMLo.woff2"
	},
	"/assets/noto-sans-devanagari-devanagari-800-normal--JKUrPzT.woff2": {
		"type": "font/woff2",
		"etag": "\"d208-ygtf+oA7V3CO1sJuf5QOrV5hP7k\"",
		"mtime": "2026-10-31T11:19:50.566Z",
		"size": 53768,
		"path": "../public/assets/noto-sans-devanagari-devanagari-800-normal--JKUrPzT.woff2"
	},
	"/assets/noto-sans-devanagari-devanagari-700-normal-v9jliTCB.woff2": {
		"type": "font/woff2",
		"etag": "\"d2e0-mnnDcobgjNJxTrDPNgJt+AFbP6I\"",
		"mtime": "2026-10-31T11:19:50.565Z",
		"size": 53984,
		"path": "../public/assets/noto-sans-devanagari-devanagari-700-normal-v9jliTCB.woff2"
	},
	"/assets/noto-sans-devanagari-devanagari-800-normal-DK92pKvO.woff": {
		"type": "font/woff",
		"etag": "\"11710-odiZXDjvSdleST6/0D5kEjIJpaQ\"",
		"mtime": "2026-10-31T11:19:50.570Z",
		"size": 71440,
		"path": "../public/assets/noto-sans-devanagari-devanagari-800-normal-DK92pKvO.woff"
	},
	"/assets/noto-sans-devanagari-devanagari-700-normal-h2KXAbYG.woff": {
		"type": "font/woff",
		"etag": "\"117e0-OxjfSJoiVpFypkgx1IUjI643yn8\"",
		"mtime": "2026-10-31T11:19:50.562Z",
		"size": 71648,
		"path": "../public/assets/noto-sans-devanagari-devanagari-700-normal-h2KXAbYG.woff"
	},
	"/assets/noto-sans-devanagari-latin-500-normal-Ca8IYteK.woff": {
		"type": "font/woff",
		"etag": "\"34b4-qWoUbLyHqTgP4YBOZpXQ1O4Ud2c\"",
		"mtime": "2026-10-31T11:19:50.573Z",
		"size": 13492,
		"path": "../public/assets/noto-sans-devanagari-latin-500-normal-Ca8IYteK.woff"
	},
	"/assets/noto-sans-devanagari-latin-400-normal-Bl6wi1XD.woff": {
		"type": "font/woff",
		"etag": "\"347c-arR989A2QPREncFvaucRB7RNIvs\"",
		"mtime": "2026-10-31T11:19:50.573Z",
		"size": 13436,
		"path": "../public/assets/noto-sans-devanagari-latin-400-normal-Bl6wi1XD.woff"
	},
	"/assets/noto-sans-devanagari-latin-600-normal-Bzmbz5CH.woff2": {
		"type": "font/woff2",
		"etag": "\"29ac-jPd2MihIC0pP8jIlXOgY/mUkfjE\"",
		"mtime": "2026-10-31T11:19:50.588Z",
		"size": 10668,
		"path": "../public/assets/noto-sans-devanagari-latin-600-normal-Bzmbz5CH.woff2"
	},
	"/assets/noto-sans-devanagari-latin-400-normal-BuiDGFlU.woff2": {
		"type": "font/woff2",
		"etag": "\"2910-sh8zsLrBocs3y66Q0+ZsX01sjGA\"",
		"mtime": "2026-10-31T11:19:50.573Z",
		"size": 10512,
		"path": "../public/assets/noto-sans-devanagari-latin-400-normal-BuiDGFlU.woff2"
	},
	"/assets/noto-sans-devanagari-latin-700-normal-B5n956PN.woff": {
		"type": "font/woff",
		"etag": "\"3490-vatZzYlB9CUCIWSkoz3AuRdLS7c\"",
		"mtime": "2026-10-31T11:19:50.596Z",
		"size": 13456,
		"path": "../public/assets/noto-sans-devanagari-latin-700-normal-B5n956PN.woff"
	},
	"/assets/noto-sans-devanagari-latin-800-normal-BTjRSi_t.woff2": {
		"type": "font/woff2",
		"etag": "\"2980-LModw4x74ynautSl2wVVQLFKClU\"",
		"mtime": "2026-10-31T11:19:50.600Z",
		"size": 10624,
		"path": "../public/assets/noto-sans-devanagari-latin-800-normal-BTjRSi_t.woff2"
	},
	"/assets/noto-sans-devanagari-latin-500-normal-DIQNxmWv.woff2": {
		"type": "font/woff2",
		"etag": "\"29e8-nN2OwHw+fQjj3S/CexvyNUd0Xec\"",
		"mtime": "2026-10-31T11:19:50.583Z",
		"size": 10728,
		"path": "../public/assets/noto-sans-devanagari-latin-500-normal-DIQNxmWv.woff2"
	},
	"/assets/noto-sans-devanagari-latin-ext-400-normal-BnQrAETZ.woff2": {
		"type": "font/woff2",
		"etag": "\"18fc-iQHijpFB3JlWEZUBVyl3iLrGW2Y\"",
		"mtime": "2026-10-31T11:19:50.613Z",
		"size": 6396,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-400-normal-BnQrAETZ.woff2"
	},
	"/assets/noto-sans-devanagari-latin-600-normal-D_YUQxD_.woff": {
		"type": "font/woff",
		"etag": "\"34bc-lIZQV82RXKZZhJBys9RhbHvSpiY\"",
		"mtime": "2026-10-31T11:19:50.590Z",
		"size": 13500,
		"path": "../public/assets/noto-sans-devanagari-latin-600-normal-D_YUQxD_.woff"
	},
	"/assets/noto-sans-devanagari-latin-700-normal-DcW8oEIt.woff2": {
		"type": "font/woff2",
		"etag": "\"296c-l7Wt/wgKnIaFCsJ6GJFJ60+/Cdw\"",
		"mtime": "2026-10-31T11:19:50.596Z",
		"size": 10604,
		"path": "../public/assets/noto-sans-devanagari-latin-700-normal-DcW8oEIt.woff2"
	},
	"/assets/noto-sans-devanagari-latin-ext-400-normal-Bs32KOJx.woff": {
		"type": "font/woff",
		"etag": "\"207c-SdcMlKz+UuukAbKnaDOulhvt5OI\"",
		"mtime": "2026-10-31T11:19:50.618Z",
		"size": 8316,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-400-normal-Bs32KOJx.woff"
	},
	"/assets/noto-sans-devanagari-latin-800-normal-CoSDk-1c.woff": {
		"type": "font/woff",
		"etag": "\"34b8-JvMP49E+RoHl8DCEootxo1iQSLg\"",
		"mtime": "2026-10-31T11:19:50.608Z",
		"size": 13496,
		"path": "../public/assets/noto-sans-devanagari-latin-800-normal-CoSDk-1c.woff"
	},
	"/assets/noto-sans-devanagari-latin-ext-600-normal-BYBXZV8b.woff": {
		"type": "font/woff",
		"etag": "\"20bc-pOTGGXA1Ni9w4pR4bRFN6PAvamk\"",
		"mtime": "2026-10-31T11:19:50.626Z",
		"size": 8380,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-600-normal-BYBXZV8b.woff"
	},
	"/assets/noto-sans-devanagari-latin-ext-500-normal-C0oyxq0s.woff2": {
		"type": "font/woff2",
		"etag": "\"190c-RU1TI02GBA+yjRlfYaxwaOzpQVI\"",
		"mtime": "2026-10-31T11:19:50.624Z",
		"size": 6412,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-500-normal-C0oyxq0s.woff2"
	},
	"/assets/noto-sans-devanagari-latin-ext-500-normal-7GrnOHW4.woff": {
		"type": "font/woff",
		"etag": "\"20a8-aV23CBi6Jt28eXKEezXhWmnXmdA\"",
		"mtime": "2026-10-31T11:19:50.620Z",
		"size": 8360,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-500-normal-7GrnOHW4.woff"
	},
	"/assets/noto-sans-devanagari-latin-ext-700-normal-DXhSwleO.woff": {
		"type": "font/woff",
		"etag": "\"20b0-+3YqV/z4NGp1KD/YoY7uu4EUXqo\"",
		"mtime": "2026-10-31T11:19:50.637Z",
		"size": 8368,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-700-normal-DXhSwleO.woff"
	},
	"/assets/noto-sans-devanagari-latin-ext-800-normal-lhg9BfoI.woff": {
		"type": "font/woff",
		"etag": "\"20b8-vRN9ueNAjM9pT6L1QiThV4bp8/s\"",
		"mtime": "2026-10-31T11:19:50.645Z",
		"size": 8376,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-800-normal-lhg9BfoI.woff"
	},
	"/assets/noto-sans-devanagari-latin-ext-700-normal-BKjKJI-9.woff2": {
		"type": "font/woff2",
		"etag": "\"192c-HZYeqMT1xtxAo/SrlsH4oVtFZwk\"",
		"mtime": "2026-10-31T11:19:50.634Z",
		"size": 6444,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-700-normal-BKjKJI-9.woff2"
	},
	"/assets/noto-sans-devanagari-latin-ext-600-normal-eCXJLagf.woff2": {
		"type": "font/woff2",
		"etag": "\"1934-mTOmx0BYPywhyY/FoC4d6Hq2TUs\"",
		"mtime": "2026-10-31T11:19:50.630Z",
		"size": 6452,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-600-normal-eCXJLagf.woff2"
	},
	"/assets/routes-Bl0lsRSP.js": {
		"type": "text/javascript; charset=utf-8",
		"etag": "\"3b286-6hnny67NVFv59p6/oGpSIXx1IcY\"",
		"mtime": "2026-10-31T11:19:50.309Z",
		"size": 242310,
		"path": "../public/assets/routes-Bl0lsRSP.js"
	},
	"/assets/noto-sans-devanagari-latin-ext-800-normal-B0pl72Pd.woff2": {
		"type": "font/woff2",
		"etag": "\"1948-jyadXsbJ+1BzBCVZcrq47gnmy8g\"",
		"mtime": "2026-10-31T11:19:50.641Z",
		"size": 6472,
		"path": "../public/assets/noto-sans-devanagari-latin-ext-800-normal-B0pl72Pd.woff2"
	},
	"/assets/styles-Bs4SG55W.css": {
		"type": "text/css; charset=utf-8",
		"etag": "\"19546-y3IxlaTndrSsHpz5qGqGCE5ZB8s\"",
		"mtime": "2026-10-31T11:19:50.649Z",
		"size": 103750,
		"path": "../public/assets/styles-Bs4SG55W.css"
	}
};
//#endregion
//#region #nitro/virtual/public-assets
var publicAssetBases = {};
function isPublicAssetURL(id = "") {
	if (public_assets_data_default[id]) return true;
	for (const base in publicAssetBases) if (id.startsWith(base)) return true;
	return false;
}
//#endregion
//#region node_modules/nitro/dist/runtime/internal/route-rules.mjs
var headers = ((m) => function headersRouteRule(event) {
	for (const [key, value] of Object.entries(m.options || {})) event.res.headers.set(key, value);
});
//#endregion
//#region #nitro/virtual/routing
var findRouteRules = /* @__PURE__ */ (() => {
	const $0 = [{
		name: "headers",
		route: "/assets/**",
		handler: headers,
		options: { "cache-control": "public, max-age=31536000, immutable" }
	}];
	return (m, p) => {
		let r = [];
		if (p.charCodeAt(p.length - 1) === 47) p = p.slice(0, -1) || "/";
		let s = p.split("/");
		if (s.length > 1) {
			if (s[1] === "assets") r.unshift({
				data: $0,
				params: { "_": s.slice(2).join("/") }
			});
		}
		return r;
	};
})();
var _lazy_bAD6ry = defineLazyEventHandler(() => import("./_chunks/ssr-renderer.mjs"));
var findRoute = /* @__PURE__ */ (() => {
	const data = {
		route: "/**",
		handler: _lazy_bAD6ry
	};
	return ((_m, p) => {
		return {
			data,
			params: { "_": p.slice(1) }
		};
	});
})();
[].filter(Boolean);
//#endregion
//#region node_modules/nitro/dist/runtime/internal/error/prod.mjs
var errorHandler = (error, event) => {
	const res = defaultHandler(error, event);
	return new FastResponse(typeof res.body === "string" ? res.body : JSON.stringify(res.body, null, 2), res);
};
function defaultHandler(error, event) {
	const unhandled = error.unhandled ?? !HTTPError.isError(error);
	const { status = 500, statusText = "" } = unhandled ? {} : error;
	if (status === 404) {
		const url = event.url || new URL(event.req.url);
		const baseURL = "/";
		if (/^\/[^/]/.test(baseURL) && !url.pathname.startsWith(baseURL)) return {
			status: 302,
			headers: new Headers({ location: `${baseURL}${url.pathname.slice(1)}${url.search}` })
		};
	}
	const headers = new Headers(unhandled ? {} : error.headers);
	headers.set("content-type", "application/json; charset=utf-8");
	return {
		status,
		statusText,
		headers,
		body: {
			error: true,
			...unhandled ? {
				status,
				unhandled: true
			} : typeof error.toJSON === "function" ? error.toJSON() : {
				status,
				statusText,
				message: error.message
			}
		}
	};
}
//#endregion
//#region #nitro/virtual/error-handler
var errorHandlers = [errorHandler];
async function error_handler_default(error, event) {
	for (const handler of errorHandlers) try {
		const response = await handler(error, event, { defaultHandler });
		if (response) return response;
	} catch (error) {
		console.error(error);
	}
}
//#endregion
//#region #nitro/virtual/app
function createNitroApp() {
	const captureError = (error, errorCtx) => {
		if (errorCtx?.event) {
			const errors = errorCtx.event.req.context?.nitro?.errors;
			if (errors) errors.push({
				error,
				context: errorCtx
			});
		}
	};
	const h3App = createH3App({ onError(error, event) {
		return error_handler_default(error, event);
	} });
	let appHandler = (req) => {
		req.context ||= {};
		req.context.nitro = req.context.nitro || { errors: [] };
		return h3App.fetch(req);
	};
	return {
		fetch: appHandler,
		h3: h3App,
		hooks: void 0,
		captureError
	};
}
function createH3App(config) {
	const h3App = new H3Core(config);
	h3App["~findRoute"] = (event) => findRoute(event.req.method, event.url.pathname);
	h3App["~getMiddleware"] = (event, route) => {
		const pathname = event.url.pathname;
		const method = event.req.method;
		const middleware = [];
		const routeRules = getRouteRules(method, pathname);
		event.context.routeRules = routeRules?.routeRules;
		if (routeRules?.routeRuleMiddleware.length) middleware.push(...routeRules.routeRuleMiddleware);
		if (route?.data?.middleware?.length) middleware.push(...route.data.middleware);
		return middleware;
	};
	return h3App;
}
//#endregion
//#region node_modules/nitro/dist/runtime/internal/app.mjs
var APP_ID = "default";
function useNitroApp() {
	let instance = useNitroApp._instance;
	if (instance) return instance;
	instance = useNitroApp._instance = createNitroApp();
	globalThis.__nitro__ = globalThis.__nitro__ || {};
	globalThis.__nitro__[APP_ID] = instance;
	return instance;
}
function useNitroHooks() {
	const nitroApp = useNitroApp();
	const hooks = nitroApp.hooks;
	if (hooks) return hooks;
	return nitroApp.hooks = new HookableCore();
}
function getRouteRules(method, pathname) {
	const m = findRouteRules(method, pathname);
	if (!m?.length) return { routeRuleMiddleware: [] };
	const routeRules = {};
	for (const layer of m) for (const rule of layer.data) {
		const currentRule = routeRules[rule.name];
		if (currentRule) {
			if (rule.options === false) {
				delete routeRules[rule.name];
				continue;
			}
			if (typeof currentRule.options === "object" && typeof rule.options === "object") currentRule.options = {
				...currentRule.options,
				...rule.options
			};
			else currentRule.options = rule.options;
			currentRule.route = rule.route;
			currentRule.params = {
				...currentRule.params,
				...layer.params
			};
		} else if (rule.options !== false) routeRules[rule.name] = {
			...rule,
			params: layer.params
		};
	}
	const middleware = [];
	const orderedRules = Object.values(routeRules).sort((a, b) => (a.handler?.order || 0) - (b.handler?.order || 0));
	for (const rule of orderedRules) {
		if (rule.options === false || !rule.handler) continue;
		middleware.push(rule.handler(rule));
	}
	return {
		routeRules,
		routeRuleMiddleware: middleware
	};
}
//#endregion
//#region node_modules/nitro/dist/presets/cloudflare/runtime/_module-handler.mjs
function createHandler(hooks) {
	const nitroApp = useNitroApp();
	const nitroHooks = useNitroHooks();
	return {
		async fetch(request, env, context) {
			globalThis.__env__ = env;
			augmentReq(request, {
				env,
				context
			});
			const ctxExt = {};
			const url = new URL(request.url);
			if (hooks.fetch) {
				const res = await hooks.fetch(request, env, context, url, ctxExt);
				if (res) return res;
			}
			return await nitroApp.fetch(request);
		},
		scheduled(controller, env, context) {
			globalThis.__env__ = env;
			context.waitUntil(nitroHooks.callHook("cloudflare:scheduled", {
				controller,
				env,
				context
			}) || Promise.resolve());
		},
		email(message, env, context) {
			globalThis.__env__ = env;
			context.waitUntil(nitroHooks.callHook("cloudflare:email", {
				message,
				event: message,
				env,
				context
			}) || Promise.resolve());
		},
		queue(batch, env, context) {
			globalThis.__env__ = env;
			context.waitUntil(nitroHooks.callHook("cloudflare:queue", {
				batch,
				event: batch,
				env,
				context
			}) || Promise.resolve());
		},
		tail(traces, env, context) {
			globalThis.__env__ = env;
			context.waitUntil(nitroHooks.callHook("cloudflare:tail", {
				traces,
				env,
				context
			}) || Promise.resolve());
		},
		trace(traces, env, context) {
			globalThis.__env__ = env;
			context.waitUntil(nitroHooks.callHook("cloudflare:trace", {
				traces,
				env,
				context
			}) || Promise.resolve());
		}
	};
}
function augmentReq(cfReq, ctx) {
	const req = cfReq;
	req.ip = cfReq.headers.get("cf-connecting-ip") || void 0;
	req.runtime ??= { name: "cloudflare" };
	req.runtime.cloudflare = {
		...req.runtime.cloudflare,
		...ctx
	};
	req.waitUntil = ctx.context?.waitUntil.bind(ctx.context);
}
//#endregion
//#region node_modules/nitro/dist/presets/cloudflare/runtime/cloudflare-module.mjs
var cloudflare_module_default = createHandler({ fetch(cfRequest, env, context, url) {
	if (env.ASSETS && isPublicAssetURL(url.pathname)) return env.ASSETS.fetch(cfRequest);
} });
//#endregion
export { cloudflare_module_default as default };
