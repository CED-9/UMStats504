import matplotlib
matplotlib.use('Agg')

import pandas as pd
import numpy as np
from deed_data import deed
import statsmodels.api as sm
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

dx = deed.copy()
dx = dx.rename(columns={"APN (Parcel Number) (unformatted)": "id", "SALE DATE": "date", "FIPS": "fips"})
dx = dx.loc[:, ["id", "date", "fips"]]

# Only consider after 1960.
dx = dx.loc[dx.date >= 0, :]

# Time from one record to the one after it
dx['tdiff'] = dx.date.diff().shift(-1)

# m is True on the last row of each group of records for one house
m = dx.id != dx.id.shift(-1)

# Last record for most houses is censored
y = (pd.to_datetime("2017-07-01") - pd.to_datetime("1960-01-01")).days
dx['tdiff'][m] = y - dx['date'][m]

# Censoring status, 1=sold, 0=censored
dx["status"] = 1
dx["status"][m] = 0

# year of prior transaction
dx["year"] = (pd.to_datetime("1960-01-01") + pd.to_timedelta(dx.date, 'd')).dt.year

dy = dx.loc[dx.tdiff > 0, :] # need to get to the bottom of this
dy.tdiff /= 365.25

sf = sm.duration.SurvfuncRight(dy.tdiff, dy.status)

spr, spt = [], []
for k,g in dy.groupby("fips"):
    if g.shape[0] < 20:
        continue
    s0 = sm.duration.SurvfuncRight(g.tdiff, g.status)
    if s0.surv_times.min() < 10 and s0.surv_times.max() > 10:
        f = interp1d(s0.surv_times, s0.surv_prob)
        if s0.surv_times.min() <=1 and s0.surv_times.max() >= 15:
            spt.append([f(t) for t in range(1, 15)])
        g = interp1d(s0.surv_times, s0.surv_prob_se)
        se = float(g(10))
        if np.isfinite(se):
            spr.append([float(f(10)), float(g(10))])
spr = np.asarray(spr)
spt = np.asarray(spt)

# Use PCA on the FIPS-level survival functions to identify the
# dominant patterns of variation.
spq = np.log(spt / (1 - spt))
spq -= spq.mean(0)
cc = np.cov(spq.T)
spc, s, vt = np.linalg.svd(cc, 0)

# Proportional hazards regression looking at effects of calendar time
# and time from previous sale.
model = sm.PHReg.from_formula("tdiff ~ bs(year, 6)", status="status", data=dy)
result = model.fit()
bhaz = result.baseline_cumulative_hazard

pdf = PdfPages("turnover.pdf")

# Plot the estimate of the overall marginal survival function
plt.clf()
plt.plot(sf.surv_times, sf.surv_prob, '-', rasterized=True)
plt.xlabel("Years", size=15)
plt.ylabel("Probability not sold", size=15)
plt.title("U.S. marginal survival function for home retention")
plt.grid(True)
pdf.savefig()

# Histogram of 10-year retention rates
plt.clf()
plt.title("10 year retention rate by FIPS")
plt.hist(spr[:,0], normed=True)

# Estimate the structural variance of the parameters
# and plot it as a normal density
va = np.var(spr[:, 0]) - np.mean(spr[:, 1]**2)
sd = np.sqrt(va)
mu = spr[:, 0].mean()
x = np.linspace(spr[:, 0].min(), spr[:, 0].max(), 30)
y = np.exp(-0.5*(x - mu)**2 / sd**2) / np.sqrt(2 * np.pi * sd**2)
plt.plot(x, y, '-', color='orange', lw=4)

plt.xlabel("Rate", size=15)
plt.ylabel("Frequency", size=15)
pdf.savefig()

# Plot all estimated survival functions for counties, after transformation
plt.clf()
y = np.arange(1, 15)
plt.title("Transformed survivor functions by FIPS region")
for i in range(spq.shape[0]):
    plt.plot(y, spq[i, :], color='grey', alpha=0.5)
plt.grid(True)
plt.xlabel("Years since purchase", size=15)
plt.ylabel("Logit probability not sold (centered)", size=15)
pdf.savefig()

# Plot the dominant two PC's of the transformed survival functions
plt.clf()
plt.title("PC's of FIPS-level survival functions")
plt.plot(spc[:,0])
plt.plot(spc[:,1])
plt.grid(True)
plt.xlabel("Time", size=15)
plt.ylabel("Loading", size=15)
pdf.savefig()

# Plot top and bottom scoring curves for the top 2 PC's
sc = np.dot(spq, spc[:, 0:2])
for k in 0,1:
    ii = np.argsort(sc[:, k])
    plt.clf()
    for i in ii[0:20]:
        plt.plot(y, spt[i, :], color='blue', alpha=0.5)
    for i in ii[-20:]:
        plt.plot(y, spt[i, :], color='red', alpha=0.5)
    plt.grid(True)
    plt.xlabel("Years since purchase", size=15)
    plt.ylabel("Probability not sold", size=15)
    plt.title("Top/bottom 20 for PC %d" % (k + 1))
    pdf.savefig()

# Plot the hazard ratio for year of purchase
plt.clf()
y = np.asarray(dy.year)[0::50]
z = result.predict().predicted_values[0::50]
ii = np.argsort(y)
plt.ylabel("Log hazard ratio", size=15)
plt.xlabel("Year", size=15)
plt.plot(y[ii], z[ii], '-', rasterized=True)
plt.grid(True)
pdf.savefig()

from scipy.misc import derivative

# Plot the baseline hazard function
plt.clf()
f = interp1d(bhaz[0][0], bhaz[0][1])
xh = np.linspace(1, 40, 40)
ha = np.asarray([derivative(f, x, dx=0.5) for x in xh])
plt.plot(xh, ha, '-')
plt.grid(True)
plt.xlabel("Years since purchase", size=15)
plt.ylabel("Baseline hazard", size=15)
pdf.savefig()

# Plot the actual hazard function for purchases made in various years
dd = pd.DataFrame({"year": [1970, 1980, 1990, 2000]})
lhr = result.predict(exog=dd).predicted_values
hr = np.exp(lhr)
plt.clf()
plt.axes([0.1, 0.1, 0.75, 0.8])
for j in range(len(hr)):
    plt.plot(xh, hr[j] * ha, label=str(dd.iloc[j,0]))
ha, lb = plt.gca().get_legend_handles_labels()
leg = plt.figlegend(ha, lb, 'center right')
leg.draw_frame(False)
plt.grid(True)
plt.xlabel("Years since purchase", size=15)
plt.ylabel("Hazard", size=15)
pdf.savefig()

pdf.close()

