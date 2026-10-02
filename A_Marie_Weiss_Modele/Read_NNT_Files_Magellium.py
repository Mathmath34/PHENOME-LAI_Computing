# -*- coding: utf-8 -*-
"""
Created on Mon May 14 17:31:02 2018

@author: mweiss
"""
#def read_NNT(filename)

import os

import pandas as pd
import numpy as np
from matplotlib import pyplot

# Tangente sigmoid
def tansig(x):
    output = 2/(1+np.exp(-2*x))-1
    return(output)

# Normalization/Denormalization
def NormDenorm(x,xmin,xmax,mode):
    if mode == "direct":
        NormVar = 2*(x-xmin)/(xmax-xmin)-1
    else: 
        NormVar = 0.5*(x+1)*(xmax-xmin)+xmin
    return(NormVar)

def Read_NNt(fileRoot, Var):
    nnt = {}
    for i in Var:
        # Lecture du fichier excel
        fileName = ''.join([fileRoot,i,'.xlsx'])
        toto={}
        # Norm Min,Max
        toto["Norm_InMin"] = pd.read_excel(fileName, 'Normalisation',header=None, skiprows = 5, skipfooter=7,index_col=None, usecols=range(1,2), na_values=['NA'],dtype='float')
        
        toto["Norm_InMax"]  = pd.read_excel(fileName, 'Normalisation',header=None, skiprows = 5, skipfooter=7,index_col=None, usecols=range(2,3), na_values=['NA'],dtype='float')
        toto["Norm_OutMin"] = pd.read_excel(fileName, 'Normalisation',header=None, skiprows = 22, index_col=None, usecols=range(1,2), na_values=['NA'],dtype='float')
        toto["Norm_OutMax"] = pd.read_excel(fileName, 'Normalisation',header=None, skiprows = 22, index_col=None, usecols=range(2,3), na_values=['NA'],dtype='float')
         
        # Weight, Bias
        toto["w_Layer1"] = pd.read_excel(fileName, 'Weights',header=None, skiprows = 5, skipfooter=7,index_col=None, usecols=range(1,12), na_values=['NA'],dtype='float')
        toto["b_Layer1"] = pd.read_excel(fileName, 'Weights',header=None,skiprows = 10, skipfooter=6,index_col=None, usecols=range(1,6), na_values=['NA'],dtype='float')
        toto["w_Layer2"] = pd.read_excel(fileName, 'Weights',header=None,skiprows = 14, skipfooter=2,index_col=None, usecols=range(1,6), na_values=['NA'],dtype='float')
        toto["b_Layer2"] = pd.read_excel(fileName, 'Weights',header=None,skiprows = 15, skipfooter=1,index_col=None, usecols=range(1,2), na_values=['NA'],dtype='float')
    
        # Extreme Cases
        toto["Tol"] = pd.read_excel(fileName, 'Extreme Cases',header=None,skiprows = 9, index_col=None, usecols=range(1,4), na_values=['NA'],dtype='float')
        
        # Definition domain
        if i=="LAI":
            tata = pd.read_excel(fileName, 'Definition_Domain',header=None,skiprows = 3, index_col=None, usecols=range(0,9), na_values=['NA'])
            nnt["CellBound"] = tata.values[0:2,1:].astype(float)
            nnt["DefDomain"] = tata.values[6:,0:tata.shape[1]-1].astype(float)
        nnt[i]=toto
    return nnt

def Apply_NNT(Input,nnt,Var):
    Output={}
    for i in Var:
        Flag = 0
        if i=="FAPAR":
            # Apply Definition Domain (input out of bounds test)
            Cell_Number = (Input[0:8]-nnt["CellBound"][0])/(nnt["CellBound"][1]-nnt["CellBound"][0])*10
            In_def = np.sum(np.abs(np.ceil(Cell_Number)-nnt["DefDomain"]),axis=1)
     
        if In_def[In_def.argmin()]!=0.0:
            Flag=1
            out  =float('nan')
        else: 
            # If definition Domain is OK, apply NNT and tolerance and output out of bounds test       
            #Normalisation Input
            InNorm = NormDenorm(np.reshape(Input,[11,1]), nnt[i]["Norm_InMin"],nnt[i]["Norm_InMax"],"direct") 
            #First Layer
            Out_1  = tansig(np.transpose(InNorm).dot(np.transpose(nnt[i]["w_Layer1"])) + nnt[i]["b_Layer1"]) 
            # Second Layer
            Out_2  = Out_1.dot(np.transpose(nnt[i]["w_Layer2"])) + nnt[i]["b_Layer2"]
            # Denormlization Output
            out    = np.squeeze(NormDenorm(Out_2, nnt[i]["Norm_OutMin"],nnt[i]["Norm_OutMax"],"reverse")) 
    
            if np.less(out,nnt[i]["Tol"][1]-nnt[i]["Tol"][0]).bool():
                out  =float('nan')
                Flag = 2
            elif np.logical_and(np.greater(out,nnt[i]["Tol"][1]-nnt[i]["Tol"][0]), np.less(out,nnt[i]["Tol"][1])).bool():
                out =nnt[i]["Tol"][1]
                Flag = 2
            if np.greater(out,nnt[i]["Tol"][2]+nnt[i]["Tol"][0]).bool():
                out=float('nan')
                Flag = 2
            elif np.logical_and(np.greater(out,nnt[i]["Tol"][2]), np.less(out,nnt[i]["Tol"][2]+nnt[i]["Tol"][0])).bool():
                out =nnt[i]["Tol"][2]
                Flag = 2
        Output[i] = [out,Flag]
    return(Output)



# Vérification sur les cas test - comparaison résultat python/matlab

cwd = os.getcwd()
Var=['FAPAR','FCOVER','LAI','LAI_Cab']
fileRoot = os.path.join(cwd, 'Algo_S2_V2.0_SL2T_')
nnt = Read_NNt(fileRoot, Var)
# Read Input
fileTest = os.path.join(cwd, 'Test_Cases_S2_V2.0_SL2T_1.xlsx')
TestCase = pd.read_excel(fileTest,header = 0, index_col=None,dtype='float')
# Loop of Input, apply NNT and check if OK
OutputPy=np.ndarray(shape=(TestCase.shape[0],4),dtype=float)
for j in range(0,250):#♣ range(TestCase.shape[0]):
     Input = np.array(TestCase.iloc[j,0:11])   
     OutputCheck = TestCase.iloc[j,11:15]
     FlagCheck = np.array(TestCase.iloc[j,15:20])
     toto=Apply_NNT(Input,nnt,Var)
     compt=0
     for i in Var:
          OutputPy[j,compt] = toto[i][0]
          compt=compt+1
      
pyplot.figure(1)
compt = 0
for i in Var:
    pyplot.subplot(2,2,compt+1)
    pyplot.scatter(TestCase.iloc[0:250,11+compt*2],OutputPy[0:5000,compt],c='green',marker='o',s=4)
    pyplot.title(i)
    compt=compt+1

pyplot.close()          