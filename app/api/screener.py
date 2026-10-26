from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
import json
import asyncio
import os
import pandas as pd

from app.engine.fetcher import analyser_action_complete, analyser_tendances_macro, obtenir_taux_sans_risque
from app.engine.math_models import dossier_graphs

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

TICKERS_PAR_INDICE = {
    "CAC 40": ["AC.PA", "AI.PA", "AIR.PA", "MT.PA", "CS.PA", "BNP.PA", "EN.PA", "BVI.PA", "CAP.PA", "CA.PA", "ACA.PA", "BN.PA", "DSY.PA", "FGA.PA", "ENGI.PA", "EL.PA", "ERF.PA", "ENX.PA", "RMS.PA", "KER.PA", "OR.PA", "LR.PA", "MC.PA", "ML.PA", "ORA.PA", "RI.PA", "PUB.PA", "RNO.PA", "SAF.PA", "SGO.PA", "SAN.PA", "SU.PA", "GLE.PA", "STLAM.PA", "STMPA.PA", "HO.PA", "TTE.PA", "URW.PA", "VIE.PA", "DG.PA"],
    "NASDAQ 100": ["AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN", "AMZN", "ANSS", "APP", "ASML", "AVGO", "AZN", "BGE", "BIIB", "BKNG", "BKR", "CCEP", "CDNS", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DLTR", "DXCM", "EA", "EBAY", "EXC", "FANG", "FAST", "FTNT", "GEHC", "GILD", "GOOG", "GOOGL", "HON", "IDXX", "ILMN", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LIN", "LRCX", "LULU", "MAR", "MCHP", "MDB", "MDLZ", "MELI", "META", "MNST", "MRNA", "MRVL", "MSFT", "MU", "NFLX", "NXPI", "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PYPL", "QCOM", "REGN", "ROST", "SBUX", "SIRI", "SMCI", "SNPS", "TEAM", "TMUS", "TSLA", "TTD", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDAY", "XEL", "ZS"],
    "Dow Jones": ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"],
    "TSX 60": ["AEM.TO", "AIF.TO", "ATD.TO", "BAM.TO", "BCE.TO", "BMO.TO", "BNS.TO", "BN.TO", "CAE.TO", "CCO.TO", "CCL-B.TO", "CG.TO", "CM.TO", "CNR.TO", "CNQ.TO", "CP.TO", "CPK.TO", "CSU.TO", "CVE.TO", "DOL.TO", "EMR.TO", "ENB.TO", "EQX.TO", "FM.TO", "FNV.TO", "FSV.TO", "GIB-A.TO", "GIL.TO", "H.TO", "IMO.TO", "IPL.TO", "K.TO", "KEY.TO", "L.TO", "MAG.TO", "MG.TO", "MFC.TO", "MRU.TO", "NA.TO", "NTR.TO", "OTEX.TO", "PAAS.TO", "PPL.TO", "POW.TO", "QSR.TO", "RCI-B.TO", "RY.TO", "SAP.TO", "SHOP.TO", "SJR-B.TO", "SLF.TO", "STN.TO", "SU.TO", "T.TO", "TD.TO", "TECK-B.TO", "TFII.TO", "TOU.TO", "TRP.TO", "WCN.TO", "WPM.TO"],
    "DAX 40": ["1COV.DE", "ADS.DE", "AIR.DE", "ALV.DE", "BAS.DE", "BAYN.DE", "BEI.DE", "BMW.DE", "BNR.DE", "CBK.DE", "CON.DE", "DB1.DE", "DBK.DE", "DHL.DE", "DTG.DE", "DTE.DE", "ENR.DE", "EOAN.DE", "FRE.DE", "HEI.DE", "HEN3.DE", "HNR1.DE", "IFX.DE", "MBG.DE", "MRK.DE", "MTX.DE", "MUV2.DE", "PAH3.DE", "PUM.DE", "QIA.DE", "RHM.DE", "RWE.DE", "SAP.DE", "SHL.DE", "SIE.DE", "SRT3.DE", "SY1.DE", "VNA.DE", "VOW3.DE", "ZAL.DE"],
    "Euro Stoxx 50": ["ADS.DE", "AD.AS", "ADYEN.AS", "AIR.PA", "ALV.DE", "AME.PA", "ASML.AS", "BAS.DE", "BAYN.DE", "BBVA.MC", "BMW.DE", "BN.PA", "BNP.PA", "CS.PA", "DB1.DE", "DHL.DE", "DTE.DE", "EL.PA", "ENEL.MI", "ENI.MI", "EOAN.DE", "FLTR.L", "HEI.DE", "IBE.MC", "IFX.DE", "INGA.AS", "ISP.MI", "ITX.MC", "KER.PA", "KNEBV.HE", "MC.PA", "MBG.DE", "MUV2.DE", "NOKIA.HE", "OR.PA", "PRX.AS", "RMS.PA", "SAF.PA", "SAN.MC", "SAN.PA", "SAP.DE", "SIE.DE", "STLAM.PA", "SU.PA", "TTE.PA", "UCG.MI", "VIE.PA", "VNA.DE", "VOW3.DE", "WKL.AS"],
    "FTSE 100": ["AAL.L", "ABF.L", "ADM.L", "AHT.L", "ANTO.L", "AUTO.L", "AV.L", "AZN.L", "BA.L", "BARC.L", "BATS.L", "BDEV.L", "BKG.L", "BP.L", "BRBY.L", "BT-A.L", "CCH.L", "CPG.L", "CRDA.L", "DCC.L", "DGE.L", "DPH.L", "ENT.L", "EXPN.L", "FCIT.L", "FLTR.L", "FRES.L", "GLEN.L", "GSK.L", "HLMA.L", "HLN.L", "HSBA.L", "HSV.L", "IAG.L", "IHG.L", "III.L", "IMB.L", "INF.L", "JD.L", "KGF.L", "LAND.L", "LGEN.L", "LLOY.L", "LSEG.L", "MNDI.L", "MNG.L", "MEL.L", "NG.L", "NWG.L", "NXT.L", "OCDO.L", "PHNX.L", "PRU.L", "PSN.L", "PSON.L", "REL.L", "RIO.L", "RKT.L", "RMV.L", "RR.L", "RS1.L", "RTO.L", "SBRY.L", "SDR.L", "SGE.L", "SGRO.L", "SHEL.L", "SMDS.L", "SMIN.L", "SN.L", "SPX.L", "SSE.L", "STAN.L", "STJ.L", "SVT.L", "TSCO.L", "TW.L", "ULVR.L", "UTG.L", "UU.L", "VOD.L", "WEIR.L", "WPP.L", "WTB.L", "FRAS.L", "HIK.L", "ITV.L", "MKS.L", "WISE.L", "EDV.L", "BME.L"],
    "FTSE MIB": ["A2A.MI", "AMP.MI", "AZM.MI", "BAMI.MI", "BMED.MI", "BPE.MI", "BZU.MI", "CPR.MI", "DIA.MI", "ENEL.MI", "ENI.MI", "ERG.MI", "RACE.MI", "FBK.MI", "G.MI", "HER.MI", "INW.MI", "ISP.MI", "IVG.MI", "LDO.MI", "MB.MI", "MONC.MI", "NEXI.MI", "PIR.MI", "PST.MI", "PRY.MI", "REC.MI", "SPM.MI", "SRG.MI", "STLAM.MI", "STMPA.MI", "TEN.MI", "TIT.MI", "TRN.MI", "UCG.MI", "UNI.MI"],
    "BEL 20": ["ABI.BR", "ACKB.BR", "AED.BR", "AGS.BR", "APAM.BR", "ARGX.BR", "BEKB.BR", "COFB.BR", "COLR.BR", "DIE.BR", "ELI.BR", "GBL.BR", "GLPG.BR", "KBC.BR", "LOTB.BR", "MELE.BR", "SOF.BR", "SOLB.BR", "SYENS.BR", "UCB.BR"],
    "OMXS30": ["ABB.ST", "ALFA.ST", "ASSA-B.ST", "ATCO-A.ST", "ATCO-B.ST", "AZN.ST", "BOL.ST", "ELUX-B.ST", "ERIC-B.ST", "ESSITY-B.ST", "EVO.ST", "GETI-B.ST", "HEXA-B.ST", "HM-B.ST", "INVE-B.ST", "KINV-B.ST", "NIBE-B.ST", "NDA-SE.ST", "SAND.ST", "SCA-B.ST", "SEB-A.ST", "SINCH.ST", "SKA-B.ST", "SKF-B.ST", "SHB-A.ST", "SWED-A.ST", "TEL2-B.ST", "TELIA.ST", "VOLV-B.ST"],
    "Nikkei 225": ["1332.T", "1605.T", "1721.T", "1801.T", "1802.T", "1803.T", "1808.T", "1812.T", "1925.T", "1928.T", "1963.T", "2002.T", "2269.T", "2282.T", "2413.T", "2432.T", "2501.T", "2502.T", "2503.T", "2531.T", "2768.T", "2801.T", "2802.T", "2871.T", "2914.T", "3086.T", "3099.T", "3289.T", "3382.T", "3401.T", "3402.T", "3405.T", "3407.T", "3861.T", "3863.T", "4004.T", "4005.T", "4021.T", "4042.T", "4043.T", "4061.T", "4063.T", "4151.T", "4183.T", "4188.T", "4208.T", "4324.T", "4452.T", "4502.T", "4503.T", "4506.T", "4507.T", "4519.T", "4523.T", "4543.T", "4568.T", "4578.T", "4689.T", "4704.T", "4751.T", "4755.T", "4901.T", "4902.T", "4911.T", "5019.T", "5020.T", "5101.T", "5108.T", "5201.T", "5214.T", "5233.T", "5301.T", "5332.T", "5333.T", "5401.T", "5406.T", "5411.T", "5541.T", "5631.T", "5703.T", "5706.T", "5711.T", "5713.T", "5714.T", "5801.T", "5802.T", "5803.T", "6098.T", "6103.T", "6113.T", "6201.T", "6273.T", "6301.T", "6302.T", "6305.T", "6326.T", "6361.T", "6367.T", "6471.T", "6472.T", "6473.T", "6501.T", "6502.T", "6503.T", "6504.T", "6506.T", "6594.T", "6674.T", "6701.T", "6702.T", "6724.T", "6752.T", "6753.T", "6758.T", "6762.T", "6770.T", "6841.T", "6857.T", "6861.T", "6902.T", "6920.T", "6952.T", "6954.T", "6971.T", "6976.T", "6981.T", "6988.T", "7003.T", "7011.T", "7012.T", "7013.T", "7201.T", "7202.T", "7203.T", "7205.T", "7211.T", "7261.T", "7267.T", "7269.T", "7270.T", "7272.T", "7731.T", "7733.T", "7735.T", "7751.T", "7752.T", "7832.T", "7911.T", "7912.T", "7951.T", "7974.T", "8001.T", "8002.T", "8015.T", "8028.T", "8031.T", "8035.T", "8053.T", "8058.T", "8233.T", "8252.T", "8253.T", "8267.T", "8304.T", "8306.T", "8308.T", "8309.T", "8316.T", "8331.T", "8354.T", "8355.T", "8411.T", "8591.T", "8601.T", "8604.T", "8628.T", "8630.T", "8697.T", "8725.T", "8750.T", "8766.T", "8801.T", "8802.T", "8804.T", "8830.T", "9001.T", "9005.T", "9007.T", "9008.T", "9009.T", "9020.T", "9021.T", "9022.T", "9064.T", "9101.T", "9104.T", "9107.T", "9201.T", "9202.T", "9301.T", "9432.T", "9433.T", "9434.T", "9501.T", "9502.T", "9503.T", "9531.T", "9532.T", "9602.T", "9613.T", "9735.T", "9766.T", "9843.T", "9983.T", "9984.T"],
    "SMI Suisse": ["ABBN.SW", "CFR.SW", "GEBN.SW", "GIVN.SW", "HOLN.SW", "LOGN.SW", "LONN.SW", "NESN.SW", "NOVN.SW", "PGHN.SW", "ROG.SW", "SCMN.SW", "SIKA.SW", "SLHN.SW", "SREN.SW", "UBSG.SW", "VATN.SW", "ZURN.SW"],
    "AEX Pays-Bas": ["AALB.AS", "ABN.AS", "AD.AS", "ADYEN.AS", "AKZA.AS", "ASML.AS", "ASRN.AS", "BESI.AS", "DSM-FIR.AS", "EXOR.AS", "HEIA.AS", "IMCD.AS", "INGA.AS", "KPN.AS", "NN.AS", "OCI.AS", "PRX.AS", "REN.AS", "SHELL.AS", "UMG.AS", "VKR.AS", "VOP.AS", "WKL.AS"],
    "Ibex 35": ["ACS.MC", "ACX.MC", "AENA.MC", "AMS.MC", "ANA.MC", "ANE.MC", "BBVA.MC", "BKN.MC", "CABK.MC", "CLNX.MC", "COL.MC", "ELE.MC", "ENG.MC", "FER.MC", "FLUI.MC", "FDR.MC", "GRF.MC", "IAG.MC", "IBE.MC", "IDR.MC", "ITX.MC", "LOG.MC", "MAP.MC", "MEL.MC", "MRL.MC", "MTS.MC", "NTR.MC", "PUIG.MC", "RED.MC", "REP.MC", "ROVI.MC", "SAB.MC", "SAN.MC", "SCYR.MC", "TEF.MC", "UNI.MC"],
    "CSI 300": ["000001.SZ", "000002.SZ", "000063.SZ", "000100.SZ", "000157.SZ", "000333.SZ", "000338.SZ", "000568.SZ", "000596.SZ", "000651.SZ", "000661.SZ", "000725.SZ", "000768.SZ", "000776.SZ", "000792.SZ", "000800.SZ", "000858.SZ", "000876.SZ", "000895.SZ", "000938.SZ", "000963.SZ", "000977.SZ", "001289.SZ", "001979.SZ", "002001.SZ", "002007.SZ", "002027.SZ", "002049.SZ", "002050.SZ", "002120.SZ", "002142.SZ", "002179.SZ", "002180.SZ", "002230.SZ", "002236.SZ", "002241.SZ", "002252.SZ", "002271.SZ", "002304.SZ", "002311.SZ", "002352.SZ", "002371.SZ", "002415.SZ", "002459.SZ", "002460.SZ", "002466.SZ", "002475.SZ", "002493.SZ", "002555.SZ", "002594.SZ", "002709.SZ", "002714.SZ", "002736.SZ", "002812.SZ", "002821.SZ", "002841.SZ", "002916.SZ", "002920.SZ", "002938.SZ", "003006.SZ", "300014.SZ", "300015.SZ", "300033.SZ", "300059.SZ", "300122.SZ", "300124.SZ", "300142.SZ", "300274.SZ", "300308.SZ", "300316.SZ", "300347.SZ", "300408.SZ", "300413.SZ", "300433.SZ", "300450.SZ", "300498.SZ", "300601.SZ", "300628.SZ", "300661.SZ", "300750.SZ", "300760.SZ", "300896.SZ", "300919.SZ", "300957.SZ", "300979.SZ", "300999.SZ", "600000.SS", "600009.SS", "600010.SS", "600011.SS", "600015.SS", "600016.SS", "600018.SS", "600019.SS", "600023.SS", "600028.SS", "600029.SS", "600030.SS", "600031.SS", "600036.SS", "600039.SS", "600048.SS", "600050.SS", "600061.SS", "600085.SS", "600089.SS", "600104.SS", "600111.SS", "600115.SS", "600132.SS", "600150.SS", "600176.SS", "600183.SS", "600188.SS", "600196.SS", "600276.SS", "600309.SS", "600346.SS", "600362.SS", "600383.SS", "600406.SS", "600426.SS", "600436.SS", "600438.SS", "600519.SS", "600547.SS", "600570.SS", "600584.SS", "600585.SS", "600588.SS", "600600.SS", "600660.SS", "600690.SS", "600703.SS", "600741.SS", "600760.SS", "600795.SS", "600803.SS", "600809.SS", "600837.SS", "600887.SS", "600893.SS", "600900.SS", "600905.SS", "600919.SS", "600926.SS", "600941.SS", "600958.SS", "600999.SS", "601006.SS", "601009.SS", "601012.SS", "601021.SS", "601066.SS", "601088.SS", "601111.SS", "601138.SS", "601166.SS", "601169.SS", "601186.SS", "601211.SS", "601225.SS", "601229.SS", "601236.SS", "601238.SS", "601288.SS", "601318.SS", "601319.SS", "601328.SS", "601336.SS", "601360.SS", "601377.SS", "601390.SS", "601398.SS", "601600.SS", "601601.SS", "601607.SS", "601618.SS", "601628.SS", "601633.SS", "601658.SS", "601668.SS", "601669.SS", "601688.SS", "601689.SS", "601727.SS", "601766.SS", "601788.SS", "601800.SS", "601816.SS", "601818.SS", "601838.SS", "601857.SS", "601877.SS", "601878.SS", "601888.SS", "601898.SS", "601899.SS", "601901.SS", "601919.SS", "601939.SS", "601985.SS", "601988.SS", "601989.SS", "601995.SS", "603259.SS", "603260.SS", "603288.SS", "603501.SS", "603659.SS", "603799.SS", "603806.SS", "603833.SS", "603899.SS", "603986.SS", "688008.SS", "688012.SS", "688036.SS", "688041.SS", "688111.SS", "688126.SS", "688187.SS", "688223.SS", "688271.SS", "688303.SS", "688363.SS", "688396.SS", "688561.SS", "688599.SS", "688981.SS"],
    "Hang Seng": ["0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK", "0066.HK", "0101.HK", "0175.HK", "0241.HK", "0267.HK", "0288.HK", "0291.HK", "0316.HK", "0386.HK", "0388.HK", "0669.HK", "0700.HK", "0762.HK", "0823.HK", "0836.HK", "0857.HK", "0868.HK", "0883.HK", "0939.HK", "0941.HK", "0960.HK", "0968.HK", "0981.HK", "0992.HK", "1038.HK", "1044.HK", "1088.HK", "1093.HK", "1109.HK", "1113.HK", "1177.HK", "1209.HK", "1211.HK", "1299.HK", "1378.HK", "1398.HK", "1810.HK", "1928.HK", "1929.HK", "1997.HK", "2015.HK", "2020.HK", "2269.HK", "2313.HK", "2318.HK", "2319.HK", "2331.HK", "2382.HK", "2388.HK", "2688.HK", "2899.HK", "3690.HK", "3968.HK", "3988.HK", "6618.HK", "6690.HK", "9618.HK", "9633.HK", "9868.HK", "9888.HK", "9961.HK", "9988.HK", "9999.HK"],
    "ASX 200": ["A2M.AX", "AGL.AX", "ALL.AX", "ALQ.AX", "ALU.AX", "AMC.AX", "AMP.AX", "ANN.AX", "ANZ.AX", "APA.AX", "APE.AX", "APT.AX", "ARB.AX", "ASX.AX", "AWC.AX", "AZJ.AX", "BAP.AX", "BEN.AX", "BGA.AX", "BHP.AX", "BIN.AX", "BKW.AX", "BLD.AX", "BOQ.AX", "BPT.AX", "BSL.AX", "BWP.AX", "BXB.AX", "CAR.AX", "CBA.AX", "CCP.AX", "CDA.AX", "CHC.AX", "CHN.AX", "CIA.AX", "CIP.AX", "CKF.AX", "CLW.AX", "CLY.AX", "CMW.AX", "CNI.AX", "COH.AX", "COL.AX", "CPU.AX", "CQE.AX", "CSL.AX", "CSR.AX", "CUV.AX", "CWY.AX", "DDR.AX", "DEG.AX", "DHG.AX", "DMP.AX", "DOW.AX", "DXS.AX", "EDV.AX", "ELD.AX", "EMR.AX", "EVN.AX", "FBU.AX", "FLT.AX", "FMG.AX", "FPH.AX", "GEM.AX", "GMG.AX", "GNC.AX", "GOR.AX", "GOZ.AX", "GPT.AX", "GNE.AX", "GWA.AX", "HLS.AX", "HVN.AX", "IAG.AX", "IEL.AX", "IFO.AX", "ING.AX", "IPH.AX", "IPL.AX", "IRE.AX", "IVC.AX", "JBHI.AX", "JHG.AX", "JHX.AX", "LFS.AX", "LNK.AX", "LYC.AX", "MFG.AX", "MGR.AX", "MIN.AX", "MP1.AX", "MPL.AX", "MQG.AX", "MMS.AX", "MND.AX", "NAN.AX", "NAB.AX", "NSR.AX", "NST.AX", "NUF.AX", "NWS.AX", "NXT.AX", "ORA.AX", "ORG.AX", "ORI.AX", "OSH.AX", "OZL.AX", "PBH.AX", "PDL.AX", "PLS.AX", "PME.AX", "PMV.AX", "PPT.AX", "PRN.AX", "QAN.AX", "QBE.AX", "QUB.AX", "REA.AX", "RHC.AX", "RIO.AX", "RMD.AX", "RNWR.AX", "RRL.AX", "RWC.AX", "S32.AX", "SCG.AX", "SCP.AX", "SDF.AX", "SGP.AX", "SGR.AX", "SHV.AX", "SIP.AX", "SKC.AX", "SKI.AX", "SLR.AX", "SOL.AX", "STO.AX", "SGM.AX", "SUN.AX", "SVW.AX", "TAH.AX", "TCL.AX", "TLS.AX", "TNE.AX", "TPG.AX", "TWE.AX", "TYR.AX", "VCX.AX", "VEA.AX", "VUK.AX", "WBC.AX", "WTC.AX", "WES.AX", "WOR.AX", "WOW.AX", "WPL.AX", "XRO.AX", "ZIP.AX"],
    "Nifty 50": ["ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS", "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BPCL.NS", "BHARTIARTL.NS", "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS", "DRREDDY.NS", "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "ITC.NS", "INDUSINDBK.NS", "INFY.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS", "LTIM.NS", "M&M.NS", "MARUTI.NS", "NTPC.NS", "NESTLEIND.NS", "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SHRIRAMFIN.NS", "SBIN.NS", "SUNPHARMA.NS", "TCS.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "TECHM.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS"],
    "Bovespa": ["ABEV3.SA", "ALOS3.SA", "AZUL4.SA", "B3SA3.SA", "BBAS3.SA", "BBDC3.SA", "BBDC4.SA", "BBSE3.SA", "BEEF3.SA", "BPAC11.SA", "BRAP4.SA", "BRFS3.SA", "BRKM5.SA", "CCRO3.SA", "CIEL3.SA", "CMIG4.SA", "CMIN3.SA", "COGN3.SA", "CPFE3.SA", "CPLE6.SA", "CRFB3.SA", "CSAN3.SA", "CSNA3.SA", "CVCB3.SA", "CYRE3.SA", "DXCO3.SA", "EGIE3.SA", "ELET3.SA", "ELET6.SA", "EMBR3.SA", "ENGI11.SA", "EQTL3.SA", "EZTC3.SA", "FLRY3.SA", "GGBR4.SA", "GOAU4.SA", "GOLL4.SA", "HAPV3.SA", "HYPE3.SA", "IGTI11.SA", "IRBR3.SA", "ITSA4.SA", "ITUB4.SA", "JBSS3.SA", "KLBN11.SA", "LREN3.SA", "LWSA3.SA", "MGLU3.SA", "MRFG3.SA", "MRVE3.SA", "MULT3.SA", "NTCO3.SA", "PCAR3.SA", "PETR3.SA", "PETR4.SA", "PETZ3.SA", "PRIO3.SA", "RADL3.SA", "RAIZ4.SA", "RDOR3.SA", "RENT3.SA", "RECV3.SA", "SANB11.SA", "SBSP3.SA", "SLCE3.SA", "SMTO3.SA", "SOMA3.SA", "SUZB3.SA", "TAEE11.SA", "TIMS3.SA", "TOTS3.SA", "UGPA3.SA", "USIM5.SA", "VALE3.SA", "VBBR3.SA", "VIIA3.SA", "VIVT3.SA", "WEGE3.SA", "YDUQ3.SA"]
}

def analyser_recommandations_tous_indices(donnees_macro):
    vix = donnees_macro.get("Volatilité VIX", 0)
    tnx = donnees_macro.get("Taux 10 Ans", 0)
    petrole = donnees_macro.get("Pétrole WTI", 0)
    or_val = donnees_macro.get("Or", 0)
    cuivre = donnees_macro.get("Cuivre", 0)
    semi = donnees_macro.get("Semi-conducteurs", 0)
    dollar = donnees_macro.get("Index Dollar", 0)

    recoms = {}
    
    # Amérique du Nord
    recoms["S&P 500"] = {"badge": "🔥 TOP SCAN" if vix < 18 else "⚪ NEUTRE", "style": "badge-top" if vix < 18 else "badge-neutral", "conseil": "Marché global US stable. Idéal pour un scan large sur les grands leaders mondiaux."}
    recoms["NASDAQ 100"] = {"badge": "⚡ OPPORTUNITÉ TECH" if (vix > 20 or tnx < -0.5) else "🟢 FAVORABLE", "style": "badge-opp" if (vix > 20 or tnx < -0.5) else "badge-fav", "conseil": "Tension/Repli sur les taux : opportunité de dénicher des pépites de croissance à prix réduit."}
    recoms["Dow Jones"] = {"badge": "🟢 VALUE SOLIDE" if tnx > 0.5 else "⚪ NEUTRE", "style": "badge-fav" if tnx > 0.5 else "badge-neutral", "conseil": "Taux soutenus : environnement idéal pour les conglomérats industriels et financières US."}
    recoms["TSX 60"] = {"badge": "🔥 BOOM MATIÈRES" if (petrole > 1.5 or or_val > 1.5) else "⚪ NEUTRE", "style": "badge-top" if (petrole > 1.5 or or_val > 1.5) else "badge-neutral", "conseil": "Énergie et métaux précieux au vert : très forte génération de Free Cash Flow au Canada."}

    # Europe
    recoms["CAC 40"] = {"badge": "🟢 BANQUES & LUXE" if tnx > 0 else "⚪ NEUTRE", "style": "badge-fav" if tnx > 0 else "badge-neutral", "conseil": "Bon niveau de spreads banques/assurance et résilience des grandes capitalisations françaises."}
    recoms["DAX 40"] = {"badge": "🔥 EXPORT DYNAMIQUE" if (dollar > 1.0 or cuivre > 1.0) else "⚪ NEUTRE", "style": "badge-top" if (dollar > 1.0 or cuivre > 1.0) else "badge-neutral", "conseil": "Dollar fort et demande industrielle soutenue : catalyseur positif pour l'export allemand."}
    recoms["Euro Stoxx 50"] = {"badge": "🟢 ÉQUILIBRE EU", "style": "badge-fav", "conseil": "Excellente diversification européenne sur les 50 champions du continent."}
    recoms["FTSE 100"] = {"badge": "🔥 RENDEMENT DIV" if (petrole > 1.0 or or_val > 1.0) else "⚪ NEUTRE", "style": "badge-top" if (petrole > 1.0 or or_val > 1.0) else "badge-neutral", "conseil": "Sur-représentation de l'énergie et des mines : rendements en dividende très généreux."}
    recoms["Ibex 35"] = {"badge": "🟢 MARGE BANCAIRE" if tnx > 0.5 else "⚪ NEUTRE", "style": "badge-fav" if tnx > 0.5 else "badge-neutral", "conseil": "Secteur bancaire espagnol très réactif aux taux d'intérêt."}
    recoms["FTSE MIB"] = {"badge": "🔥 SECTEUR BANQUE" if tnx > 0.8 else "⚪ NEUTRE", "style": "badge-top" if tnx > 0.8 else "badge-neutral", "conseil": "Forte rentabilité des banques italiennes portée par les taux obligataires."}
    recoms["AEX Pays-Bas"] = {"badge": "⚡ SEMI-CONDUCTEURS" if semi > 1.0 else "🟢 FAVORABLE", "style": "badge-opp" if semi > 1.0 else "badge-fav", "conseil": "Indice porté par les géants mondiaux des puces électroniques (ASML)."}
    recoms["BEL 20"] = {"badge": "🛡️ REFUGE PHARMA" if vix > 18 else "⚪ NEUTRE", "style": "badge-safe" if vix > 18 else "badge-neutral", "conseil": "Profil défensif (santé/holdings), idéal si la nervosité monte sur les marchés."}
    recoms["SMI Suisse"] = {"badge": "🛡️ REFUGE ABSOLU" if vix > 20 else "🟢 HAUTE QUALITÉ", "style": "badge-safe" if vix > 20 else "badge-fav", "conseil": "Les plus beaux bilans d'Europe (Roche, Nestlé, Novartis). Stabilité maximale."}
    recoms["OMXS30"] = {"badge": "🟢 INGÉNIERIE NORD", "style": "badge-fav", "conseil": "Excellente efficacité opérationnelle et ROI élevé sur l'industrie scandinave."}

    # Asie & Émergents
    recoms["Nikkei 225"] = {"badge": "🔥 YEN FAIBLE / EXPORT" if dollar > 1.0 else "🟢 FAVORABLE", "style": "badge-top" if dollar > 1.0 else "badge-fav", "conseil": "Gouvernance d'entreprise améliorée et dynamisme des exportateurs japonais."}
    recoms["Hang Seng"] = {"badge": "⚡ DÉCOOTE EXTRÊME" if vix < 20 else "⚠️ VOLATILITÉ", "style": "badge-opp" if vix < 20 else "badge-warn", "conseil": "Multiples de valorisation (PER) extrêmement bas sur les géants tech chinois."}
    recoms["CSI 300"] = {"badge": "⚡ OPPORTUNITÉ RELANCE" if cuivre > 0 else "⚪ NEUTRE", "style": "badge-opp" if cuivre > 0 else "badge-neutral", "conseil": "Marché intérieur chinois à fort potentiel de rebond comptable."}
    recoms["ASX 200"] = {"badge": "🔥 MINES & FER" if (or_val > 0.5 or cuivre > 0.5) else "🟢 FAVORABLE", "style": "badge-top" if (or_val > 0.5 or cuivre > 0.5) else "badge-fav", "conseil": "Secteur minier australien ultra-rentable avec marges brutales."}
    recoms["Nifty 50"] = {"badge": "🚀 MEGA-CROISSANCE", "style": "badge-top", "conseil": "Expansion économique indienne la plus rapide des grandes puissances."}
    recoms["Bovespa"] = {"badge": "🔥 COMMODITIES" if petrole > 1.0 else "⚪ NEUTRE", "style": "badge-top" if petrole > 1.0 else "badge-neutral", "conseil": "Valorisations très bon marché sur les géants brésiliens des matières premières."}
    return recoms

@router.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    donnees_macro = await asyncio.to_thread(analyser_tendances_macro)
    recoms = analyser_recommandations_tous_indices(donnees_macro)
    tops = [k for k, v in recoms.items() if "🔥" in v["badge"] or "⚡" in v["badge"]][:2]
    top_text = " • ".join(tops) if tops else "CAC 40 • S&P 500"
    return templates.TemplateResponse(request, "index.html", {"recoms": recoms, "top_text": top_text})

@router.get("/run", response_class=HTMLResponse)
async def dashboard_view(request: Request, indice: str = "CAC 40", secteur: str = ""):
    return templates.TemplateResponse(request, "dashboard.html", {"indice": indice, "secteur": secteur})

@router.get("/stream")
async def flux_donnees_temps_reel(indice: str = "CAC 40", secteur: str = ""):
    secteurs_cibles = [secteur] if secteur else []
    
    donnees_macro = await asyncio.to_thread(analyser_tendances_macro)
    taux_du_jour = await asyncio.to_thread(obtenir_taux_sans_risque)
    
    if indice == "S&P 500":
        try:
            df_tickers = pd.read_csv("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv")
            tickers = [str(t).replace(".", "-") for t in df_tickers['Symbol'].dropna()]
        except Exception as e:
            print(f"Erreur chargement S&P 500: {e}")
            tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX", "AMD", "INTC"]
    
    elif indice in TICKERS_PAR_INDICE:
        # On pioche dans ton dictionnaire si l'indice existe
        tickers = TICKERS_PAR_INDICE[indice]
        
    else:
        # Sécurité ultime par défaut
        tickers = ["MC.PA", "TTE.PA", "AI.PA"]

    
    async def generer_analyses():
        for ticker in tickers:
            resultat = await asyncio.to_thread(analyser_action_complete, ticker, secteurs_cibles, taux_du_jour, donnees_macro)
            if resultat:
                yield f"data: {json.dumps(resultat)}\n\n"
            await asyncio.sleep(0.1)
        yield "event: close\ndata: end\n\n"

    return StreamingResponse(generer_analyses(), media_type="text/event-stream")

@router.get("/graphs/{fichier}")
async def lire_graphique(fichier: str):
    chemin = os.path.join(dossier_graphs, fichier)
    if os.path.exists(chemin): return FileResponse(chemin)
    return HTMLResponse(content="Graphique introuvable", status_code=404)