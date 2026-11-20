// kicad-review: the board in 3D for the board page (board.html). kicad-cli exports the board with its parts' 3D models
// as one GLB (pcb export glb, kireview_board.export_3d); this draws it with WebGL2, without a library. The GLB is in
// metres with Y up; board mm map as x -> X and y -> Z (both times 1000), up -> Y. The nodes of the parts are named by
// their reference (R1, U3, ...): each part gets an id, kept per vertex, so a part can be tinted, hidden or picked.
'use strict';
const Board3D = (() => {
  const FOV = 30 * Math.PI / 180;       // vertical field of view
  const TURN = 0.008;                   // radians per px of a drag
  const ZOOM = 1.0015;                  // per wheel delta
  const ALPHA_OPAQUE = 0.85;            // a see-through material this solid or more is drawn opaque (the silkscreen, 0.9)
  // views: [yaw, pitch]. From below, the board turns over left to right, as KiCad shows the back
  const VIEWS = { top: [0, Math.PI / 2], bottom: [Math.PI, -Math.PI / 2], iso: [-0.45, 0.7] };
  const HOVER = 1, SEL = 2, HL = 3;     // a part's state, per part in a texture

  // ---------------------------------------------------------------- vectors and matrices (column-major, like GL)
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  function mat4mul(a, b) {
    const o = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  }
  // a node's own transform: its matrix, or translation, rotation (quaternion) and scale
  function trs(n) {
    if (n.matrix) return n.matrix.slice();
    const [x, y, z, w] = n.rotation || [0, 0, 0, 1], [sx, sy, sz] = n.scale || [1, 1, 1], t = n.translation || [0, 0, 0];
    return [(1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0,
      2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
      2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
      t[0], t[1], t[2], 1];
  }
  // the matrix for normals: the inverse transpose of the upper 3x3 (columns: b x c, c x a, a x b over the determinant)
  function normalMatrix(m) {
    const a = [m[0], m[1], m[2]], b = [m[4], m[5], m[6]], c = [m[8], m[9], m[10]];
    const d = dot(a, cross(b, c)) || 1;
    return [...mul(cross(b, c), 1 / d), ...mul(cross(c, a), 1 / d), ...mul(cross(a, b), 1 / d)];
  }

  // ---------------------------------------------------------------- GLB
  function parseGlb(buf) {
    const dv = new DataView(buf);
    if (buf.byteLength < 20 || dv.getUint32(0, true) !== 0x46546C67) throw new Error('not a GLB file');
    let off = 12, json = null, bin = 0;
    while (off + 8 <= dv.byteLength) {
      const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true);
      if (type === 0x4E4F534A) json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off + 8, len)));
      else if (type === 0x004E4942) bin = off + 8;
      off += 8 + len;
    }
    if (!json) throw new Error('GLB without JSON');
    return { buf, json, bin };
  }
  const NCOMP = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
  const CTYPE = { 5120: [Int8Array, 'getInt8'], 5121: [Uint8Array, 'getUint8'], 5122: [Int16Array, 'getInt16'],
    5123: [Uint16Array, 'getUint16'], 5125: [Uint32Array, 'getUint32'], 5126: [Float32Array, 'getFloat32'] };
  // an accessor's values, flat (count x components)
  function accessor(g, i) {
    const a = g.json.accessors[i], n = NCOMP[a.type], [T, get] = CTYPE[a.componentType];
    if (a.bufferView === undefined) return new T(a.count * n);
    const bv = g.json.bufferViews[a.bufferView], size = T.BYTES_PER_ELEMENT;
    const start = g.bin + (bv.byteOffset || 0) + (a.byteOffset || 0), stride = bv.byteStride || n * size;
    if (stride === n * size && start % size === 0) return new T(g.buf, start, a.count * n);
    const out = new T(a.count * n), dv = new DataView(g.buf);
    for (let k = 0; k < a.count; k++) for (let c = 0; c < n; c++) out[k * n + c] = dv[get](start + k * stride + c * size, true);
    return out;
  }

  // the scene in board mm, flattened into two batches (opaque, see-through), each one draw call: positions, normals,
  // colours (linear, 0..255), part ids (0: the board)
  function build(g) {
    const J = g.json, parts = [], jobs = [];
    const toMM = [1000, 0, 0, 0, 0, 1000, 0, 0, 0, 0, 1000, 0, 0, 0, 0, 1];
    const walk = (ni, parent, depth, id) => {
      const n = J.nodes[ni], m = mat4mul(parent, trs(n));
      if (depth === 1 && n.name && !n.name.startsWith('=>')) { parts.push(n.name); id = parts.length; }
      if (n.mesh !== undefined) {
        for (const p of J.meshes[n.mesh].primitives) {
          if ((p.mode !== undefined && p.mode !== 4) || p.attributes.POSITION === undefined) continue;
          const mt = p.material !== undefined ? J.materials[p.material] : {};
          const c = (mt.pbrMetallicRoughness || {}).baseColorFactor || [1, 1, 1, 1];
          jobs.push({ p, m, id, c, blend: mt.alphaMode === 'BLEND' && c[3] < ALPHA_OPAQUE });
        }
      }
      for (const ch of n.children || []) walk(ch, m, depth + 1, id);
    };
    const scene = J.scenes ? J.scenes[J.scene || 0] : { nodes: J.nodes.map((_, i) => i) };
    for (const r of scene.nodes) walk(r, toMM, 0, 0);
    const batches = [false, true].map(blend => {
      const js = jobs.filter(j => j.blend === blend);
      let nv = 0, ni = 0;
      for (const j of js) {
        const cnt = J.accessors[j.p.attributes.POSITION].count;
        nv += cnt;
        ni += j.p.indices !== undefined ? J.accessors[j.p.indices].count : cnt;
      }
      return { jobs: js, pos: new Float32Array(nv * 3), nrm: new Float32Array(nv * 3), col: new Uint8Array(nv * 4),
        part: new Uint16Array(nv), idx: new Uint32Array(ni), v: 0, i: 0 };
    });
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];        // the board's
    const alo = [Infinity, Infinity, Infinity], ahi = [-Infinity, -Infinity, -Infinity];      // everything's
    for (const B of batches) {
      for (const j of B.jobs) {
        const pos = accessor(g, j.p.attributes.POSITION);
        const nrm = j.p.attributes.NORMAL !== undefined ? accessor(g, j.p.attributes.NORMAL) : null;
        const idx = j.p.indices !== undefined ? accessor(g, j.p.indices) : null;
        const m = j.m, nm = normalMatrix(m), base = B.v, nv = pos.length / 3;
        const col = j.c.map(x => Math.round(Math.max(0, Math.min(1, x)) * 255));
        for (let k = 0; k < nv; k++) {
          const x = pos[3 * k], y = pos[3 * k + 1], z = pos[3 * k + 2], o = 3 * (base + k);
          const X = m[0] * x + m[4] * y + m[8] * z + m[12], Y = m[1] * x + m[5] * y + m[9] * z + m[13];
          const Z = m[2] * x + m[6] * y + m[10] * z + m[14];
          B.pos[o] = X; B.pos[o + 1] = Y; B.pos[o + 2] = Z;
          const b0 = j.id ? alo : lo, b1 = j.id ? ahi : hi;
          if (X < b0[0]) b0[0] = X; if (Y < b0[1]) b0[1] = Y; if (Z < b0[2]) b0[2] = Z;
          if (X > b1[0]) b1[0] = X; if (Y > b1[1]) b1[1] = Y; if (Z > b1[2]) b1[2] = Z;
          if (nrm) {
            const a = nrm[3 * k], b = nrm[3 * k + 1], c = nrm[3 * k + 2];
            const u = nm[0] * a + nm[3] * b + nm[6] * c, v = nm[1] * a + nm[4] * b + nm[7] * c, w = nm[2] * a + nm[5] * b + nm[8] * c;
            const l = Math.hypot(u, v, w) || 1;
            B.nrm[o] = u / l; B.nrm[o + 1] = v / l; B.nrm[o + 2] = w / l;
          }
          B.col.set(col, 4 * (base + k));
          B.part[base + k] = j.id;
        }
        const ni = idx ? idx.length : nv;
        for (let t = 0; t < ni; t++) B.idx[B.i + t] = base + (idx ? idx[t] : t);
        if (!nrm) faceNormals(B, base, nv, B.i, ni);
        B.v += nv;
        B.i += ni;
      }
    }
    if (lo[0] === Infinity) { lo.splice(0, 3, ...alo); hi.splice(0, 3, ...ahi); }
    for (let k = 0; k < 3; k++) { alo[k] = Math.min(alo[k], lo[k]); ahi[k] = Math.max(ahi[k], hi[k]); }
    return { parts, batches, board: [lo, hi], all: [alo, ahi] };
  }
  // a primitive without normals: each vertex gets the sum of its triangles' normals
  function faceNormals(B, base, nv, i0, ni) {
    const P = B.pos, N = B.nrm;
    for (let t = i0; t + 2 < i0 + ni; t += 3) {
      const a = 3 * B.idx[t], b = 3 * B.idx[t + 1], c = 3 * B.idx[t + 2];
      const n = cross([P[b] - P[a], P[b + 1] - P[a + 1], P[b + 2] - P[a + 2]], [P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]]);
      for (const v of [a, b, c]) { N[v] += n[0]; N[v + 1] += n[1]; N[v + 2] += n[2]; }
    }
    for (let k = base; k < base + nv; k++) {
      const o = 3 * k, l = Math.hypot(N[o], N[o + 1], N[o + 2]) || 1;
      N[o] /= l; N[o + 1] /= l; N[o + 2] /= l;
    }
  }

  // ---------------------------------------------------------------- shaders
  const VS = `#version 300 es
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNrm;
layout(location = 2) in vec4 aCol;
layout(location = 3) in uint aPart;
uniform mat4 uVP;
uniform highp usampler2D uState;
uniform bool uParts;
out vec3 vP; out vec3 vN; out vec4 vC;
flat out uint vS; flat out uint vId;
void main() {
  vId = aPart;
  vS = aPart == 0u ? 0u : texelFetch(uState, ivec2(int(aPart & 255u), int(aPart >> 8)), 0).r;
  vP = aPos; vN = aNrm; vC = aCol;
  gl_Position = (aPart != 0u && !uParts) ? vec4(0.0, 0.0, 2.0, 1.0) : uVP * vec4(aPos, 1.0);
}`;
  // light from the eye, and a little more on faces turned up; colours are linear, written as sRGB
  const FS = `#version 300 es
precision highp float;
in vec3 vP; in vec3 vN; in vec4 vC;
flat in uint vS;
uniform vec3 uEye; uniform vec3 uSel; uniform vec3 uHl; uniform bool uBlend;
out vec4 o;
void main() {
  vec3 n = normalize(vN), v = normalize(uEye - vP);
  if (dot(n, v) < 0.0) n = -n;
  float d = max(dot(n, v), 0.0);
  vec3 c = vC.rgb * (0.30 + 0.20 * (n.y * 0.5 + 0.5) + 0.55 * d);
  if (vS == 1u) c = mix(c, vec3(0.55, 0.75, 1.0), 0.35);
  else if (vS == 2u) c = mix(c, uSel, 0.45);
  else if (vS == 3u) c = mix(c, uHl, 0.45);
  c = pow(c, vec3(1.0 / 2.2));
  o = uBlend ? vec4(c * vC.a, vC.a) : vec4(c, 1.0);
}`;
  // picking: the part id (16 bits) and the distance along the view (16 bits of the far distance)
  const FS_PICK = `#version 300 es
precision highp float;
in vec3 vP;
flat in uint vId;
uniform vec3 uEye; uniform vec3 uFwd; uniform float uFar;
out vec4 o;
void main() {
  uint z = uint(clamp(dot(vP - uEye, uFwd) / uFar, 0.0, 1.0) * 65534.0);
  o = vec4(float(vId & 255u), float((vId >> 8) & 255u), float(z & 255u), float(z >> 8)) / 255.0;
}`;

  function program(gl, vs, fs) {
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {};
    for (let i = 0; i < gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i++) {
      const name = gl.getActiveUniform(p, i).name;
      u[name] = gl.getUniformLocation(p, name);
    }
    return { p, u };
  }

  // '#rrggbb' to a linear colour
  const linear = hex => [1, 3, 5].map(i => Math.pow(parseInt(hex.slice(i, i + 2), 16) / 255, 2.2));

  // ---------------------------------------------------------------- the view
  // opts: onView() after each frame (the page redraws its markers), onHover(hit | null), onClick(px, py, event)
  function create(canvas, opts) {
    const gl = canvas.getContext('webgl2', { antialias: true, premultipliedAlpha: true });
    if (!gl) return { ok: false };
    let draw, pick;
    try { draw = program(gl, VS, FS); pick = program(gl, VS, FS_PICK); }
    catch (err) { return { ok: false, error: err.message }; }
    let model = null;              // {parts, ids: ref -> id, gpu: [opaque, blend], board, all, top, bottom, size}
    let showParts = true;
    let marks = { sel: [], selColor: '#ffd400', hl: null }, hover = null;
    const cam = { t: [0, 0, 0], yaw: VIEWS.top[0], pitch: VIEWS.top[1], dist: 100 };
    let W = 1, H = 1, cw = 1, ch = 1, frame = 0;
    const stex = gl.createTexture();
    let state = new Uint8Array(256);
    const fb = { fb: gl.createFramebuffer(), col: gl.createRenderbuffer(), dep: gl.createRenderbuffer(), w: 0, h: 0 };

    function size() {
      const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      cw = Math.max(1, r.width); ch = Math.max(1, r.height);
      const w = Math.max(1, Math.round(cw * dpr)), h = Math.max(1, Math.round(ch * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      W = w; H = h;
    }

    // the camera: turns around its target (yaw about up, pitch above the board), dist away
    function basis() {
      const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch), cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw);
      const back = [cp * sy, sp, cp * cy], up = [-sp * sy, cp, -sp * cy], fwd = mul(back, -1);
      return { back, up, fwd, right: cross(fwd, up), eye: add(cam.t, mul(back, cam.dist)) };
    }
    function matrices() {
      const b = basis(), aspect = cw / ch, near = Math.max(0.01, cam.dist * 0.02);
      const far = cam.dist * 2 + (model ? model.size : 100) * 3, f = 1 / Math.tan(FOV / 2);
      const { right: r, up: u, back: k, eye: e } = b;
      const view = [r[0], u[0], k[0], 0, r[1], u[1], k[1], 0, r[2], u[2], k[2], 0, -dot(r, e), -dot(u, e), -dot(k, e), 1];
      const proj = [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0];
      return Object.assign(b, { vp: new Float32Array(mat4mul(proj, view)), far, aspect });
    }

    function upload(B) {
      const vao = gl.createVertexArray(), bufs = [];
      gl.bindVertexArray(vao);
      const attr = (data, loc, n, type, norm, int) => {
        const b = gl.createBuffer();
        bufs.push(b);
        gl.bindBuffer(gl.ARRAY_BUFFER, b);
        gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc);
        if (int) gl.vertexAttribIPointer(loc, n, type, 0, 0);
        else gl.vertexAttribPointer(loc, n, type, norm, 0, 0);
      };
      attr(B.pos, 0, 3, gl.FLOAT, false);
      attr(B.nrm, 1, 3, gl.FLOAT, false);
      attr(B.col, 2, 4, gl.UNSIGNED_BYTE, true);
      attr(B.part, 3, 1, gl.UNSIGNED_SHORT, false, true);
      const ib = gl.createBuffer();
      bufs.push(ib);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, B.idx, gl.STATIC_DRAW);
      gl.bindVertexArray(null);
      return { vao, bufs, n: B.idx.length };
    }
    function free() {
      if (!model) return;
      for (const g of model.gpu) { gl.deleteVertexArray(g.vao); g.bufs.forEach(b => gl.deleteBuffer(b)); }
    }

    // the parts' states (hover, selected, shown from a link) in a texture of 256 x rows
    function pushStates() {
      if (!model) return;
      state.fill(0);
      for (const r of marks.sel) { const id = model.ids[r]; if (id) state[id] = SEL; }
      if (marks.hl && model.ids[marks.hl]) state[model.ids[marks.hl]] = HL;
      if (hover && model.ids[hover]) state[model.ids[hover]] = HOVER;
      gl.bindTexture(gl.TEXTURE_2D, stex);
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 256, state.length / 256, gl.RED_INTEGER, gl.UNSIGNED_BYTE, state);
    }

    function uniforms(prog, m) {
      gl.useProgram(prog.p);
      gl.uniformMatrix4fv(prog.u.uVP, false, m.vp);
      gl.uniform1i(prog.u.uParts, showParts ? 1 : 0);
      gl.uniform3fv(prog.u.uEye, m.eye);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, stex);
      gl.uniform1i(prog.u.uState, 0);
    }
    function batches(list) {
      for (const g of list) {
        if (!g.n) continue;
        gl.bindVertexArray(g.vao);
        gl.drawElements(gl.TRIANGLES, g.n, gl.UNSIGNED_INT, 0);
      }
      gl.bindVertexArray(null);
    }

    function render() {
      frame = 0;
      size();
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      if (model) {
        const m = matrices();
        uniforms(draw, m);
        gl.uniform3fv(draw.u.uSel, linear(marks.selColor));
        gl.uniform3fv(draw.u.uHl, linear(marks.hlColor || '#ff00aa'));
        gl.enable(gl.DEPTH_TEST);
        gl.disable(gl.BLEND);
        gl.depthMask(true);
        gl.uniform1i(draw.u.uBlend, 0);
        batches([model.gpu[0]]);
        gl.enable(gl.BLEND);           // the soldermask and other see-through parts, over what is drawn
        gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.depthMask(false);
        gl.uniform1i(draw.u.uBlend, 1);
        batches([model.gpu[1]]);
        gl.depthMask(true);
        gl.disable(gl.BLEND);
      }
      if (opts.onView) opts.onView();
    }
    function redraw() { if (!frame) frame = requestAnimationFrame(render); }

    // what is under a point of the canvas (css px): {ref (null: the board), x, y (board mm), h (mm above the bottom)}
    function pickAt(px, py) {
      if (!model) return null;
      size();
      if (fb.w !== W || fb.h !== H) {
        gl.bindRenderbuffer(gl.RENDERBUFFER, fb.col);
        gl.renderbufferStorage(gl.RENDERBUFFER, gl.RGBA8, W, H);
        gl.bindRenderbuffer(gl.RENDERBUFFER, fb.dep);
        gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, W, H);
        gl.bindFramebuffer(gl.FRAMEBUFFER, fb.fb);
        gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.RENDERBUFFER, fb.col);
        gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, fb.dep);
        fb.w = W; fb.h = H;
      }
      const dpr = W / cw, x = Math.min(W - 1, Math.max(0, Math.floor(px * dpr))), y = Math.min(H - 1, Math.max(0, H - 1 - Math.floor(py * dpr)));
      const m = matrices();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb.fb);
      gl.viewport(0, 0, W, H);
      gl.enable(gl.SCISSOR_TEST);
      gl.scissor(x, y, 1, 1);
      gl.clearColor(0, 0, 1, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      uniforms(pick, m);
      gl.uniform3fv(pick.u.uFwd, m.fwd);
      gl.uniform1f(pick.u.uFar, m.far);
      gl.enable(gl.DEPTH_TEST);
      gl.disable(gl.BLEND);
      batches(model.gpu);
      const px4 = new Uint8Array(4);
      gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px4);
      gl.disable(gl.SCISSOR_TEST);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      const z = px4[2] | (px4[3] << 8);
      if (z >= 65535) return null;
      const id = px4[0] | (px4[1] << 8), dz = z / 65534 * m.far, th = Math.tan(FOV / 2);
      const nx = px / cw * 2 - 1, ny = 1 - py / ch * 2;
      const dir = add(m.fwd, add(mul(m.right, nx * th * m.aspect), mul(m.up, ny * th)));
      const p = add(m.eye, mul(dir, dz));
      return { ref: id ? model.parts[id - 1] : null, x: p[0], y: p[2], h: p[1] - model.bottom };
    }

    // ---------------------------------------------------------------- mouse: turn, move, zoom, hover, click
    let drag = null, hoverAt = null, hoverFrame = 0;
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('pointerdown', e => {
      if (!model) return;
      drag = { x: e.clientX, y: e.clientY, lx: e.clientX, ly: e.clientY, btn: e.button, pan: e.button !== 0 || e.shiftKey, moved: false };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', e => {
      const r = canvas.getBoundingClientRect();
      if (!drag) {
        hoverAt = [e.clientX - r.left, e.clientY - r.top];
        if (!hoverFrame) hoverFrame = requestAnimationFrame(doHover);
        return;
      }
      if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4) return;
      if (!drag.moved) { drag.moved = true; canvas.classList.add('drag'); }
      const dx = e.clientX - drag.lx, dy = e.clientY - drag.ly;
      drag.lx = e.clientX; drag.ly = e.clientY;
      if (drag.pan) {
        const b = basis(), k = 2 * cam.dist * Math.tan(FOV / 2) / ch;
        cam.t = add(cam.t, add(mul(b.right, -dx * k), mul(b.up, dy * k)));
      } else {
        cam.yaw -= dx * TURN;
        cam.pitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, cam.pitch + dy * TURN));
      }
      redraw();
    });
    const endDrag = e => {
      if (!drag) return;
      const d = drag;
      drag = null;
      canvas.classList.remove('drag');
      if (!d.moved && d.btn === 0 && e.type === 'pointerup' && opts.onClick) {
        const r = canvas.getBoundingClientRect();
        opts.onClick(e.clientX - r.left, e.clientY - r.top, e);
      }
    };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('pointerleave', () => { hoverAt = null; if (!drag) setHover(null, null); });
    canvas.addEventListener('wheel', e => {
      if (!model) return;
      e.preventDefault();
      const r = canvas.getBoundingClientRect(), hit = pickAt(e.clientX - r.left, e.clientY - r.top);
      let f = Math.pow(ZOOM, e.deltaY);
      const dist = Math.max(0.5, Math.min(model.size * 8, cam.dist * f));
      f = dist / cam.dist;
      // scale the camera about the point under the mouse, so that point stays where it is on screen
      const p = hit ? [hit.x, hit.h + model.bottom, hit.y] : cam.t;
      cam.t = add(p, mul(add(cam.t, mul(p, -1)), f));
      cam.dist = dist;
      redraw();
    }, { passive: false });
    function doHover() {
      hoverFrame = 0;
      if (!hoverAt || drag || !model) return;
      const hit = pickAt(hoverAt[0], hoverAt[1]);
      setHover(hit && hit.ref, hit);
    }
    function setHover(ref, hit) {
      if (ref !== hover) { hover = ref; pushStates(); redraw(); }
      if (opts.onHover) opts.onHover(hit);
    }
    new ResizeObserver(() => redraw()).observe(canvas);

    // ---------------------------------------------------------------- what the page calls
    function height(side) { return side === 'F' ? model.top : side === 'B' ? model.bottom : (model.top + model.bottom) / 2; }
    const api = {
      ok: true,
      loaded: () => !!model,
      // a GLB (ArrayBuffer): replaces the model shown; returns the refs of the parts in it
      load(buf) {
        const m = build(parseGlb(buf));
        const gpu = m.batches.map(upload);
        free();
        const [lo, hi] = m.board;
        model = { parts: m.parts, ids: {}, gpu, top: hi[1], bottom: lo[1],
          box: [lo[0], lo[2], hi[0], hi[2]], size: Math.hypot(hi[0] - lo[0], hi[2] - lo[2]) || 100 };
        m.parts.forEach((r, i) => { model.ids[r] = i + 1; });
        const rows = Math.ceil((m.parts.length + 1) / 256);
        state = new Uint8Array(256 * rows);
        gl.bindTexture(gl.TEXTURE_2D, stex);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8UI, 256, rows, 0, gl.RED_INTEGER, gl.UNSIGNED_BYTE, state);
        hover = null;
        pushStates();
        redraw();
        return m.parts.slice();
      },
      // sel: refs of the selected item (tinted selColor, '#rrggbb'), hl: a part shown from a link (hlColor)
      setMarks(m) { marks = Object.assign({ sel: [], selColor: '#ffd400', hl: null, hlColor: '#ff00aa' }, m); pushStates(); redraw(); },
      showParts(on) { showParts = !!on; redraw(); },
      // look from a side (top, bottom, iso), keeping the place looked at
      view(name) { const v = VIEWS[name]; if (!v) return; cam.yaw = v[0]; cam.pitch = v[1]; redraw(); },
      fit() {
        if (!model) return;
        size();
        const [x0, y0, x1, y1] = model.box, th = Math.tan(FOV / 2);
        cam.t = [(x0 + x1) / 2, (model.top + model.bottom) / 2, (y0 + y1) / 2];
        cam.dist = Math.max((x1 - x0) / (cw / ch), y1 - y0) / 2 / th * 1.12 + (model.top - model.bottom);
        redraw();
      },
      // show the board point (x, y) on side F / B / an inner layer, about span mm across; turn the board over when
      // that side faces away
      focus(x, y, side, span) {
        if (!model) return;
        size();
        cam.t = [x, height(side), y];
        cam.dist = span / 2 / (Math.tan(FOV / 2) * Math.min(1, cw / ch));
        if ((side === 'B' && cam.pitch > 0) || (side === 'F' && cam.pitch < 0)) { cam.yaw += Math.PI; cam.pitch = -cam.pitch; }
        redraw();
      },
      // the board point (x, y) on a side as canvas css px, or null (behind the camera)
      project(x, y, side) {
        if (!model) return null;
        const v = matrices().vp, p = [x, height(side), y];
        const X = v[0] * p[0] + v[4] * p[1] + v[8] * p[2] + v[12], Y = v[1] * p[0] + v[5] * p[1] + v[9] * p[2] + v[13];
        const w = v[3] * p[0] + v[7] * p[1] + v[11] * p[2] + v[15];
        return w > 1e-6 ? [(X / w + 1) / 2 * cw, (1 - Y / w) / 2 * ch] : null;
      },
      // the side the camera looks at: 'F' from above, 'B' from below
      side() { return model && basis().eye[1] < (model.top + model.bottom) / 2 ? 'B' : 'F'; },
      pick: pickAt,
      camera: () => ({ t: cam.t.slice(), yaw: cam.yaw, pitch: cam.pitch, dist: cam.dist }),
      setCamera(c) {
        if (!c || !Array.isArray(c.t) || ![c.yaw, c.pitch, c.dist].every(Number.isFinite)) return false;
        Object.assign(cam, { t: c.t.slice(0, 3), yaw: c.yaw, pitch: c.pitch, dist: c.dist });
        redraw();
        return true;
      },
      redraw,
    };
    return api;
  }

  return { create };
})();
