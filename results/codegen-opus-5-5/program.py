import sys, json, os, time
import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize
from scipy.ndimage import map_coordinates

def height_params(h_asc):
    h = np.asarray(h_asc, float)
    M = h.size
    h = h - h.mean()
    hd = h[::-1]
    out = {}
    out['Sa'] = np.mean(np.abs(h)); Sq = np.sqrt(np.mean(h**2)); out['Sq'] = Sq
    out['Ssk'] = np.mean(h**3)/Sq**3; out['Sku'] = np.mean(h**4)/Sq**4
    out['Sp'] = hd[0]; out['Sv'] = -hd[-1]; out['Sz'] = hd[0]-hd[-1]
    p = (np.arange(M)+0.5)/M
    w = int(round(0.4*M))
    slopes = (hd[w:]-hd[:-w])/(w/M)
    i = int(np.argmax(slopes))
    s = slopes[i]
    up = hd[i] + s*(0-p[i]); lo = hd[i] + s*(1-p[i])
    out['Sk'] = up-lo
    Smr1 = np.mean(hd > up); Smr2 = np.mean(hd > lo)
    out['Smr1'] = Smr1*100; out['Smr2'] = Smr2*100
    A1 = np.sum(np.clip(hd-up, 0, None))/M
    A2 = np.sum(np.clip(lo-hd, 0, None))/M
    out['Spk'] = 2*A1/max(Smr1, 1e-9); out['Svk'] = 2*A2/max(1-Smr2, 1e-9)
    cs = np.concatenate([[0], np.cumsum(hd)])
    def Vm(pp):
        k = int(round(pp*M)); return (cs[k] - k*hd[k])/M
    def Vv(pp):
        k = int(round(pp*M)); return ((M-k)*hd[k] - (cs[M]-cs[k]))/M
    out['Vmp'] = Vm(0.1); out['Vmc'] = Vm(0.8)-Vm(0.1)
    out['Vvc'] = Vv(0.1)-Vv(0.8); out['Vvv'] = Vv(0.8)
    return out

def loss_terms(m, t):
    L = 0.0
    W = {'Sa':3,'Sq':4,'Ssk':2,'Sku':2,'Sp':1,'Sv':1,'Sz':0.5,'Sk':1,'Spk':1,'Svk':1,
         'Smr1':0.7,'Smr2':0.7,'Vmp':1,'Vmc':1,'Vvc':1,'Vvv':1}
    for k, wt in W.items():
        if k not in t: continue
        tv = t[k]; mv = m[k]
        if k == 'Ssk':
            L += wt*((mv-tv)/max(0.3, abs(tv)))**2
        elif k == 'Smr2':
            a = max(100-tv, 1e-3); b = max(100-mv, 1e-3)
            L += wt*np.log(b/a)**2
        else:
            if tv <= 0: continue
            L += wt*np.log(max(mv, 1e-12)/tv)**2
    return L

def fit_distribution(t, N):
    Sq = t.get('Sq', 1.0)
    K = 25
    zk = np.linspace(-5.4, 5.4, K)
    M = 20000
    zM = norm.ppf((np.arange(M)+0.5)/M)
    zext = norm.ppf(np.array([0.5/N, 1-0.5/N]))
    def build(x, z):
        inc = np.exp(x[1:]); hk = np.concatenate([[0], np.cumsum(inc)]) * np.exp(x[0])
        return np.interp(z, zk, hk)
    def evalp(x):
        h = build(x, zM); mu = h.mean()
        m = height_params(h)
        e = build(x, zext) - mu
        m['Sp'] = e[1]; m['Sv'] = -e[0]; m['Sz'] = e[1]-e[0]
        return m
    x0 = np.concatenate([[np.log(Sq)], np.log(np.diff(zk))])
    f = lambda x: loss_terms(evalp(x), t)
    best = x0; bl = f(x0)
    for it in range(4):
        try:
            r = minimize(f, best, method='Powell', options={'maxfev': 6000, 'xtol':1e-4, 'ftol':1e-9})
            if r.fun < bl: best, bl = r.x, r.fun
            r = minimize(f, best, method='Nelder-Mead', options={'maxfev': 4000, 'xatol':1e-5,'fatol':1e-10, 'adaptive':True})
            if r.fun < bl: best, bl = r.x, r.fun
        except Exception:
            pass
    zN = norm.ppf((np.arange(N)+0.5)/N)
    vals = build(best, zN)
    vals = vals - vals.mean()
    if 'Sp' in t and 'Sv' in t:
        vals = np.clip(vals, -t['Sv'], t['Sp'])
        vals[-1] = t['Sp']; vals[0] = -t['Sv']
        vals = vals - vals.mean()
    return np.sort(vals), bl

def gen_field(rows, cols, dx, Ls, Ll, alpha, theta_deg, W):
    P, Q = W.shape
    lr = np.arange(P); lr = np.where(lr > P//2, lr-P, lr)*dx
    lc = np.arange(Q); lc = np.where(lc > Q//2, lc-Q, lc)*dx
    Y, X = np.meshgrid(lr, lc, indexing='ij')
    th = np.deg2rad(theta_deg)
    a = X*np.cos(th) + Y*np.sin(th)
    c = -X*np.sin(th) + Y*np.cos(th)
    r = np.sqrt((c/Ls)**2 + (a/Ll)**2)
    R = np.exp(-r**alpha)
    S = np.clip(np.fft.fft2(R).real, 0, None)
    f = np.fft.ifft2(np.fft.fft2(W)*np.sqrt(S)).real
    return f[:rows, :cols]

def rank_map(field, vals):
    out = np.empty(field.size)
    out[np.argsort(field.ravel(), kind='stable')] = vals
    return out.reshape(field.shape)

def spatial_params(z, dx):
    z = z - z.mean()
    r, c = z.shape
    F = np.fft.fft2(z, s=(2*r, 2*c))
    acf = np.fft.ifft2(np.abs(F)**2).real
    acf = np.fft.fftshift(acf/acf[0, 0])
    cy, cx = r, c
    rmax = min(r, c) - 2
    rs = np.arange(0, rmax, 0.5)
    angs = np.arange(0, 180, 0.5)
    lens = np.zeros(len(angs))
    for j, a in enumerate(angs):
        th = np.deg2rad(a)
        yy = cy + rs*np.sin(th); xx = cx + rs*np.cos(th)
        v = map_coordinates(acf, [yy, xx], order=1)
        idx = np.nonzero(v < 0.2)[0]
        if len(idx) == 0: lens[j] = rmax
        else:
            k = idx[0]
            r0, r1 = rs[k-1], rs[k]; v0, v1 = v[k-1], v[k]
            lens[j] = r0 + (v0-0.2)/(v0-v1)*(r1-r0)
    Sal = lens.min()*dx; Str = lens.min()/lens.max(); Std = angs[np.argmax(lens)]
    gy, gx = np.gradient(z, dx)
    g2 = gx**2+gy**2
    return {'Sal': Sal, 'Str': Str, 'Std': Std, 'Sdq': np.sqrt(g2.mean()),
            'Sdr': np.mean(np.sqrt(1+g2)-1)*100}

def main():
    t0 = time.time()
    inp = json.load(open(sys.argv[1])); od = sys.argv[2]
    os.makedirs(od, exist_ok=True)
    rows, cols, dx = int(inp['rows']), int(inp['cols']), float(inp['dx_um'])
    p1 = inp.get('stage1_params', {}); p2 = inp.get('stage2_params', {})
    N = rows*cols
    vals, bl = fit_distribution(p1, N)
    rng = np.random.default_rng(12345)
    W = rng.standard_normal((2*rows, 2*cols))
    f1 = gen_field(rows, cols, dx, 8*dx, 8*dx, 2.0, 0.0, W)
    z1 = rank_map(f1, vals)
    np.savetxt(os.path.join(od, 'stage1.csv'), z1, delimiter=',', fmt='%.6g')
    np.savetxt(os.path.join(od, 'stage2.csv'), z1, delimiter=',', fmt='%.6g')
    Sal_t = p2.get('Sal', 10*dx)
    if not (Sal_t and Sal_t > 0): Sal_t = 10*dx
    Str_t = min(max(p2.get('Str', 1.0) or 1.0, 1e-3), 1.0)
    Std_t = p2.get('Std', 0.0) or 0.0
    Sdq_t = p2.get('Sdq', None)
    if Sdq_t is not None and Sdq_t <= 0: Sdq_t = None
    ext = max(rows, cols)*dx
    def build(alpha, Ls, Ll):
        f = gen_field(rows, cols, dx, Ls, Ll, alpha, Std_t, W)
        z = rank_map(f, vals)
        return z, spatial_params(z, dx)
    def inner(alpha, Ls, Ll):
        for k in range(3):
            z, m = build(alpha, Ls, Ll)
            Ls *= Sal_t/max(m['Sal'], 1e-9)
            if Str_t < 0.98:
                Ll = min(Ll*(m['Str']/Str_t)**0.7 if m['Str'] > 0 else Ll, 5*ext)
                Ll = max(Ll, Ls)
            else:
                Ll = Ls
        z, m = build(alpha, Ls, Ll)
        return z, m, Ls, Ll
    alpha = 2.0
    Ls = Sal_t/np.log(5)**(1/alpha); Ll = min(Ls/Str_t, 5*ext)
    best = None
    lo, hi = 0.3, 2.0
    for it in range(9):
        if time.time()-t0 > 400: break
        z, m, Ls, Ll = inner(alpha, Ls, Ll)
        err = abs(np.log(m['Sal']/Sal_t)) + (abs(np.log(m['Sdq']/Sdq_t)) if Sdq_t else 0) \
              + 0.3*abs(np.log(max(m['Str'],1e-6)/Str_t))
        if best is None or err < best[0]: best = (err, z, m)
        if not Sdq_t: break
        if m['Sdq'] > Sdq_t: lo = alpha
        else: hi = alpha
        alpha = 0.5*(lo+hi)
    z2 = best[1]
    np.savetxt(os.path.join(od, 'stage2.csv'), z2, delimiter=',', fmt='%.6g')

if __name__ == '__main__':
    main()
