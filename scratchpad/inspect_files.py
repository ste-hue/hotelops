import sys, os, datetime, glob
import warnings; warnings.filterwarnings("ignore")
try:
    import pandas as pd
except Exception as e:
    print("no pandas:", e); sys.exit(1)

cands = [
    # Esolver
    "~/Desktop/INTUR_GENNAIO_2026_.xls",
    "~/Desktop/movimentiinturesolver.XLS",
    "~/Downloads/ListaMovimentiConto.xls",
    "~/Downloads/movimenti.xlsx",
    "~/Downloads/03069 - INTESA SANPAOLO SPA.xlsx",
    # Production / PowerBI HotelCube
    "~/Downloads/Data from Power BI.xlsx",
    "~/Downloads/Data from Power BI (2).xlsx",
    "~/Downloads/Daily Production Report (2).xlsx",
    "~/Downloads/Daily Production Report (3).xlsx",
    "~/Downloads/Panorama2_Daily Production Report (5).xlsx",
    "~/Downloads/Panorama_1_2025_Data from Power BI (2).xlsx",
    "~/Downloads/Panorama_2_2025_Data from Power BI (2).xlsx",
    "~/Downloads/CVM_1_2025_Data from Power BI (2).xlsx",
    "~/Downloads/CVM_2_2025_Data.xlsx",
    "~/Downloads/cvm.xlsx",
    "~/Downloads/ANGELINA_2_2025.xlsx",
    "~/Downloads/Produzione Netta Dashboard.xlsx",
    # Ristocube
    "~/Downloads/Consumi Articoli F&B Data.xlsx",
    "~/Downloads/Dashboard Manager.xlsx",
    "~/Downloads/Dashboard Jun 11 2026.xlsx",
]

def find_dates(df):
    lo=hi=None
    for c in df.columns:
        s = df[c]
        try:
            d = pd.to_datetime(s, errors="coerce", dayfirst=True)
            good = d.dropna()
            if len(good) >= max(3, len(df)//4):
                cmin,cmax = good.min(), good.max()
                if 2020 <= cmin.year <= 2027:
                    if lo is None or cmin<lo: lo=cmin
                    if hi is None or cmax>hi: hi=cmax
        except Exception: pass
    return (lo,hi)

for p in cands:
    fp = os.path.expanduser(p)
    if not os.path.exists(fp):
        print(f"\n### MISSING: {p}"); continue
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d")
    sz = os.path.getsize(fp)//1024
    print(f"\n### {os.path.basename(fp)}  [mtime {mt}, {sz}KB]")
    try:
        xl = pd.ExcelFile(fp)
        print("  sheets:", xl.sheet_names[:6])
        sh = xl.sheet_names[0]
        df = xl.parse(sh, nrows=200, header=0)
        print(f"  '{sh}' cols({len(df.columns)}):", [str(c)[:22] for c in df.columns[:12]])
        lo,hi = find_dates(df)
        if lo is not None:
            print(f"  date range (first 200 rows): {lo.date()} → {hi.date()}")
    except Exception as e:
        print("  ERR:", str(e)[:120])
