#!/usr/bin/env python
# coding: utf-8

# **/!\ If you are on windows, you must unzip the .gz file under Linux, or use a good gzip decompress**

# In[52]:


import math
import numpy as np
import pandas as pd

import os
import gzip

#from mpl_toolkits.basemap import Basemap
#import scipy.io
#import cv2


# In[18]:


dir_shp = r'C:\Users\thepe\Documents\Data_Analyse\Fichiers_Geolocalisation\departements-20160218-shp'
file_shp = 'departements-20160218.shp'

# In[19]:


liste_radar = {36 : 'NOYAL', 37 : 'AJACCIO', '38' : 'ST-REMY', 40 : 'ABBEVILLE', 41 : 'BORDEAUX', 42 : 'BOURGES', 43 : 'MOUCHEROTTE', 44 : 'BRIVE GREZES', 45 : 'FALAISE CAEN' , 47 : 'RADAR NANCY',
               49 : 'RADAR NIMES', 50 : 'TOULOUSE', 51 : 'TRAPPES', 52 : 'ARCIS TROYES', 53 : 'SEMBADEL', 54 : 'TREILLIERES', 55 : 'BOLLENE', 56 : 'PLABENNEC', 57 : 'OPOUL', 58 : 'ST.NIZIER',
               59 : 'COLLOBRIERES', 60 : 'VARS', 61 : 'ALERIA', 62 : 'MONTCLAR', 63 : "L'AVESNOIS", 64 : 'CHERVES', 65 : 'BLAISY-HAUT', 66 : 'MOMUY', 67 : 'MONTANCY', 68 : 'MAUREL',
               69 : 'COLOMBIS', 90 : 'GUADELOUPE LE MOULE', 91 : 'MARTINIQUE', 92 : 'LA RÉUNION COLORADO', 93: 'LA REUNION PITON VILLERS', 94 : 'NOUVELLE-CALÉDONIE NOUMEA', 96 : 'NOUVELLE-CALÉDONIE LIFOU'}


# # Functions Bufr

# In[20]:


class BitReader(object):
    # to read bit by bit (and not only byte by byte)
    def __init__(self, f):
        self.input = f
        self.accumulator = 0
        self.bcount = 0
        self.read = 0
        self.total_read = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def _readbit(self):
        if not self.bcount:
            a = self.input.read(1)
            if a:
                self.accumulator = ord(a)
            self.bcount = 8
            self.read = len(a)
        rv = (self.accumulator & (1 << self.bcount-1)) >> self.bcount-1
        self.bcount -= 1
        return rv

    def readbits(self, n):
        self.total_read += 1
        v = 0
        while n > 0:
            v = (v << 1) | self._readbit()
            n -= 1
        
        return v

def bits2bytes(chaine):    
    ent = int(chaine,2)    
    byte_number = ent.bit_length()
    bin_array= ent.to_bytes(byte_number, "big") 
    bin_array = bin_array.strip(b'\0')
    return bin_array.decode() 
    
# to decode the real 'F' and 'X' value of a descriptor
def bytes_desc(byt):    
    if byt < 64:
        return '0-' + str(byt) + '-'
    elif byt < 128:
        return '1-' + str(byt-64) + '-'
    elif byt < 192:
        return '2-' + str(byt-128) + '-'
    else:
        return '3-' + str(byt-192) + '-'

# In[21]:


# To read the csv files and put them into a dataframe
def tables_b(file_path):
    try:
        col_names_b = ['F', 'X', 'Y', 'Description', 'Unit', 'Scale', 'Reference_Value', 'Data_width_bits']
        dfb = pd.read_csv(file_path, sep = ';', header = None , names = col_names_b)
    except Exception as e:
            print(e.message)
    return dfb

def tables_d(file_path):
    col_names_d = ['F', 'X', 'Y', 'dF', 'dX', 'dY']
    dfd = pd.read_csv(file_path, sep = ';', header = None, names = col_names_d, usecols = [0,1,2,3,4,5])    
    return dfd


# In[22]:


# To stock the dataframes tables into dictionary of descriptors

# Table B : descriptors with F = 0
def dico_descriptor_b(df0):
    dico_desc = {}
    try:
        for idx, row in df0.iterrows():
            dico_desc[str(row['F'])+"-"+str(row['X'])+"-"+str(row['Y'])] = {'Description' : row['Description'], 'Unit':row['Unit'], 'Scale': row['Scale'], 'Ref_Val':row['Reference_Value'], 'Data_width_bits':row['Data_width_bits']}    
    except Exception as e:
            print(e.message)
    return dico_desc

# Table D : descriptors with F = 3 (each descriptor is a list of descriptors)
def dico_descriptor_d(df0):    
    key1 = ''
    dico_desc = {}
    listed = []
    for i in range(df0.shape[0]):        
        if not(pd.isna(df0.loc[i, 'F'])) and df0.loc[i, 'F'][-1] == '3':   
            dico_desc[key1] = listed
            listed = []            
            key1 = '3-' + str(int(df0.loc[i, 'X'])) + '-' + str(int(df0.loc[i, 'Y']))
            listed = [str(int(df0.loc[i, 'dF'])) + '-' + str(int(df0.loc[i, 'dX'])) + '-' + str(int(df0.loc[i, 'dY']))]
        elif not(pd.isna(df0.loc[i,'dF'])):
            listed += [str(int(df0.loc[i, 'dF'])) + '-' + str(int(df0.loc[i, 'dX'])) + '-' + str(int(df0.loc[i, 'dY']))]
        
    dico_desc[key1] = listed
    return dico_desc


# In[23]:


# to get the value, or the list of descriptors, contained in a descriptor
def descri(desc, affiche):    
    if desc in dico_l_b:
        r=dico_l_b[desc]
        if affiche:
            print(desc, ' : ', r)
        return r
    elif desc in dico_l_d:
        r=dico_l_d[desc]
        if affiche:
            print(desc, ' : ',r )
        return r
        
    elif desc in dico_m_b:
        r=dico_m_b[desc]
        if affiche:
            print(desc, ' : ', r)
        return r
    elif desc in dico_m_d:
        r=dico_m_d[desc]
        if affiche:
            print(desc, ' : ', r)
        return r
    else:
        r='UNKNOWN'
        if affiche:
            print(desc, ' UNKNOWN')
        return r

# to decode, and get the value contained in a simple descriptor (F = 0)
def simple_desc(desc_elt):
    global  reader, compte, fin_affichage, affiche_descriptors, datas_total, last_description, datas_unites #datas_prob_rain, datas_height_rain, datas_horizon_refle
    descript_elt = descri(desc_elt, not(fin_affichage) and affiche_descriptors)
    if type(descript_elt) is dict:
        if bit_new_width == 0:
            longueur = descript_elt['Data_width_bits'] + bit_width_plus
        else:
            longueur = bit_new_width
        description = descript_elt['Description']
        if not(fin_affichage) and affiche_descriptors:
            print('longueur : ', longueur, ' - Description : ', description)   
            
        tot_bits = reader.readbits(longueur)

        # apply the reference value and the scale to the value of the data pointed by the descriptor
        if bit_ref_changed:
            if desc_elt in bit_new_ref:
                val_data = (tot_bits + bit_new_ref[desc_elt])/10**(float(descript_elt['Scale'])+bit_scale_plus)
            else:
                # just to avoid an error, set a default value to 0
                val_data = 0                
        else:
            val_data = (tot_bits + float(descript_elt['Ref_Val']) )/10**(float(descript_elt['Scale'])+bit_scale_plus)

        if descript_elt['Unit'] == 'CCITT IA5': #compte==0:
            try:
                val_data = bits2bytes(bin(tot_bits))
                print('  "', bits2bytes(bin(tot_bits)), '"')            
            except:
                pass
        elif not(fin_affichage) and affiche_descriptors:
                print('  = ', val_data, descript_elt['Unit'])

        # stock the value in the list of values
        if description in datas_total:
            datas_total[description] += [val_data]
        else:
            datas_total[description] = [val_data]

        # stock the unit
        if not(description in datas_unites):            
            datas_unites[description] = descript_elt['Unit']

        # if we want to print all the details
        if description == last_description:
            fin_affichage = True
        else:
            fin_affichage = False

        last_description = description

# In[24]:


# Different bufr versions
def section1_v2():
    global reader, BYTES, sect2
    x = reader.readbits(3*BYTES)
    LENGTH_1 = x
    print('Length of section 1 : ', x)
    x = reader.readbits(1*BYTES)
    BUFR_MASTER_TABLE = x
    print('Bufr master table : ', x)
    x = reader.readbits(1*BYTES)
    SUB_CENTER_ID = x
    print('Identification of originating/generating sub-centre : ', x)
    x = reader.readbits(1*BYTES)
    CENTER_ID = x
    print('Identification of originating/generating centre : ', x)
    x = reader.readbits(1*BYTES)
    print('Update sequence number : ', x)
    x = reader.readbits(1*BYTES)
    sect2 = x
    print('Optional (1) / No Optional (0) section follows : ', x)
    
    if sect2:
        print('oui ya section 2')
    else:
        print('no section 2 found')
        
    x = reader.readbits(1*BYTES)
    print('Data Category (Table A) : ', x)
    x = reader.readbits(1*BYTES)
    print('Data category sub-category : ', x)
    return LENGTH_1, BUFR_MASTER_TABLE, SUB_CENTER_ID, CENTER_ID

def section1_v4():
    global reader, BYTES, sect2
    x = reader.readbits(3*BYTES)
    LENGTH_1 = x
    print('Length of section 1 : ', x)
    x = reader.readbits(1*BYTES)
    BUFR_MASTER_TABLE = x
    print('Bufr master table : ', x)
    x = reader.readbits(2*BYTES)
    CENTER_ID = x
    print('Identification of originating/generating centre : ', x)
    x = reader.readbits(2*BYTES)
    SUB_CENTER_ID = x
    print('Identification of originating/generating sub-centre : ', x)
    x = reader.readbits(1*BYTES)
    print('Update sequence number : ', x)
    x = reader.readbits(1*BYTES)
    print('Optional (1) / No Optional (0) section follows : ', x)
    x = reader.readbits(1*BYTES)
    print('Data Category (Table A) : ', x)
    x = reader.readbits(1*BYTES)
    print('International data sub-category : ', x)
    x = reader.readbits(1*BYTES)
    print('Local sub-category : ', x)
    return LENGTH_1, BUFR_MASTER_TABLE, SUB_CENTER_ID, CENTER_ID

# additional datas at the end of section 1
def section1end(version, LENGTH_1):
    global reader, BYTES
    if version == 2:
        lim = 17
    elif version == 4:
        lim = 22
    if LENGTH_1> lim:
        print('SECTION 1 ending : ')
        for k in range(LENGTH_1 - lim):
            x = reader.readbits(1*BYTES)
            print(x, ' ', chr(x)) 
        print('END OF SECTION 1')

# optional section 2
def section2():
    global reader, BYTES
    x = reader.readbits(3*BYTES)
    LENGTH_2 = x
    print('Length of section 2 : ', x)
    x = reader.readbits(1*BYTES) # set to 0 (reserved)
    for k in range(LENGTH_2 - 4):
        x = reader.readbits(1*BYTES)
        print(x, ' ', chr(x))
        
    print(' END OF SECTION 2')
        
    
    

# In[25]:


def descri_tableC():
    global descriptors, index_descript, bit_width_plus, bit_ref_changed, reader, bit_new_ref, bit_new_width, bit_scale_plus
    new_ref = int(descriptors[index_descript].split('-')[2])        
    if descriptors[index_descript].split('-')[1] == '1': 
        # change data width
        if new_ref == 0:
            bit_width_plus = 0
        else:
            bit_width_plus = new_ref - 128
    elif descriptors[index_descript].split('-')[1] == '2': 
        # change scale
        if new_ref == 0:
            bit_scale_plus = 0
        else:
            bit_scale_plus = new_ref - 128
    elif descriptors[index_descript].split('-')[1] == '3':
        # change reference value
        if 0 < new_ref:
            bit_ref_changed = True
            ybits = int(descriptors[index_descript].split('-')[2])
            index_descript += 1
            desc_new = descriptors[index_descript]
            while desc_new != '2-3-255':
                result = reader.readbits(ybits)
                if result >= 2**(ybits-1):
                    bit_new_ref[desc_new] = -1*(result - 2**(ybits-1))
                else:
                    bit_new_ref[desc_new] = result
                index_descript += 1
                desc_new = descriptors[index_descript]   
    
        else:
            bit_ref_changed = False                
            bit_new_ref = {}

    elif descriptors[index_descript].split('-')[1] == '8':
        if new_ref == 0:
            bit_new_width = 0
        else:
            bit_new_width = 8*new_ref                  
    pass

# In[62]:


def deco_bufr():
    global FILE_PATH, BYTES, bits_data, index_descript, descriptors, compte, blocs_repetes, nb_repetitions, bit_width_plus, bit_new_width, bit_scale_plus, bit_new_ref, bit_ref_changed, datas_total, datas_unites, last_description, fin_affichage, bufr_number, datas_messages, dico_m_b, dico_m_d, dico_l_b, dico_l_d, reader, sect2
  
    FILE_PATH = os.path.join(DIR_PATH, FILE_NAME)
    BYTES = 8
    bits_data = ""
    index_descript = 0
    compte = 0
    blocs_repetes  = 0
    nb_repetitions = 0
    bit_width_plus = 0
    bit_new_width = 0
    bit_scale_plus = 0
    bit_new_ref = {}
    bit_ref_changed = False
    datas_total = {}
    last_description = ''    
    fin_affichage = False    
    bufr_number = 0
    datas_messages = []
    sect2 = False
    
    # a compressed file, use (but you won't decode the 6th message of a PAM file):
    #with gzip.open(FILE_PATH, 'rb') as infile:
    # an uncompressed file, simply use:
    with open(FILE_PATH, 'rb') as infile:
        
        with BitReader(infile) as reader:
            while True:
                datas_total = {}
                datas_unites = {}
                index_descript = 0
                
                # IDENTIFICATION SECTION
                try:
                    x = reader.readbits(4*BYTES)
                except:
                    break                
                if not(str(bin(x))=="0b1000010010101010100011001010010"): # entete BUFR
                    break
                print(' ----------- BEGIN OF BUFR MESSAGE n°', bufr_number, ' -----------') 
                entete = bits2bytes(bin(x))           
                print(entete)
                
                x = reader.readbits(3*BYTES)                
                print('Total length of Bufr message in bytes : ', x)
                x = reader.readbits(1*BYTES)
                print('Bufr Edition number : ', x)

                # SECTION 1
                if str(bin(x))=="0b10":
                    version = 2
                    LENGTH_1, BUFR_MASTER_TABLE, SUB_CENTER_ID, CENTER_ID = section1_v2()
                elif str(bin(x))=="0b100":
                    version = 4
                    LENGTH_1, BUFR_MASTER_TABLE, SUB_CENTER_ID, CENTER_ID = section1_v4()
                else:
                    print('Version Inconnue')
                    break         
                                    
                x = reader.readbits(1*BYTES)
                MASTER_TABLE_NUMBER = x
                print('Version number of master table used : ', x)
                x = reader.readbits(1*BYTES)
                LOCAL_TABLE_NUMBER = x
                print('Version number of local tables used : ', x)
        
                # LOAD USEFUL TABLES
                try:                
                    table_b = tables_b(os.path.join(DIR_PATH_TABLE, FIC_TAB_B.format(master=MASTER_TABLE_NUMBER)))                
                    dico_m_b = dico_descriptor_b(table_b)
                except:
                    print(' ** UNABLE TO READ MASTER TABLE B ', MASTER_TABLE_NUMBER)
                    dico_m_b = {}
                try:
                    table_d = tables_d(os.path.join(DIR_PATH_TABLE, FIC_TAB_D.format(master=MASTER_TABLE_NUMBER)))                    
                    dico_m_d = dico_descriptor_d(table_d)                    
                except:
                    print(' ** UNABLE TO READ MASTER TABLE D', MASTER_TABLE_NUMBER)
                    dico_m_d = {}
                try:                    
                    local_table_b = tables_b(os.path.join(DIR_PATH_TABLE, FIC_LOCAL_TAB_B.format(center=CENTER_ID, local=LOCAL_TABLE_NUMBER)))
                    dico_l_b = dico_descriptor_b(local_table_b)
                except:
                    print(' ** UNABLE TO READ LOCAL TABLE B ' ,CENTER_ID ,"_" , LOCAL_TABLE_NUMBER)
                    dico_l_b = {}
                try:                    
                    local_table_d = tables_d(os.path.join(DIR_PATH_TABLE, FIC_LOCAL_TAB_D.format(center=CENTER_ID, local=LOCAL_TABLE_NUMBER)))
                    dico_l_d = dico_descriptor_d(local_table_d)                    
                except:
                    print(' ** UNABLE TO READ LOCAL TABLE D ' , CENTER_ID ,"_" , LOCAL_TABLE_NUMBER)
                    dico_l_d = {}                        
                
                if version == 2:
                    x = reader.readbits(1*BYTES)
                    print('Year : ', x)
                elif version == 4:
                    x = reader.readbits(2*BYTES)
                    print('Year : ', x)
                    
                x = reader.readbits(1*BYTES)
                print('Month : ', x)
                x = reader.readbits(1*BYTES)
                print('Day : ', x)
                x = reader.readbits(1*BYTES)
                print('Hour : ', x)
                x = reader.readbits(1*BYTES)
                print('Minute : ', x)
                if version == 4:
                    x = reader.readbits(1*BYTES)
                    print('Second : ', x)                     
        
                # END OF SECTION 1                
                section1end(version, LENGTH_1) 

                # OPTIONAL SECTION 2
                if sect2:
                    section2()
                
                    
                # SECTION 3 ( Data Description )
                x = reader.readbits(3*BYTES)
                LENGTH_3 = x
                print('Length of section 3 (Data Description) : ', x)
                x = reader.readbits(1*BYTES) # SET TO 0 (reserved)
                x = reader.readbits(2*BYTES)
                print('Number of data subsets : ', x)
                x = reader.readbits(1*BYTES)
                #if version == 2:
                print('Observed/Compressed Data : ', x//128 , '/', (x//64)%2)
                
                descriptors = []
                desc = ''
                        
                for i, k in enumerate(range(LENGTH_3 - 7)):
                    x = reader.readbits(1*BYTES)
                    if i%2 == 1:
                        desc += str(x)
                        descriptors += [desc]
                        desc = ''
                    else:
                        desc = bytes_desc(x)
        
                if affiche_descriptors:
                    print('Descriptors :')
                    print(descriptors)
        
                # SECTION 4 ( Datas )
                x = reader.readbits(3*BYTES)
                LENGTH_4 = x
                print('Length of section 4 (Datas) : ', x)
                x = reader.readbits(1*BYTES) # SET TO 0 (reserved)
        
                while True:
                    if index_descript >= len(descriptors):
                        print(' END OF DESCRIPTORS ')
                        break
                    if not(fin_affichage) and affiche_descriptors:
                        print(descriptors[index_descript])                        
                                
                    if descriptors[index_descript][0] == '0': 
                        # F = 0 : single element descriptor (ref in Table B)
                        simple_desc(descriptors[index_descript])
                                
                    elif descriptors[index_descript][0] == '3': 
                        # F = 3 : list of descriptors (ref in table D)
                        descript_elt = descri(descriptors[index_descript], not(fin_affichage) and affiche_descriptors)
                        for eltk in descript_elt:
                            if affiche_descriptors:
                                print(eltk)
                        # insert the list of descriptors in place of the descriptor
                        descriptors = descriptors[:index_descript] + descript_elt + descriptors[index_descript+1:]                            
                        index_descript -= 1
                        
                    elif descriptors[index_descript][0] == '2':
                        # F = 2 : Operator descriptor  (ref in table C)                        
                        descri_tableC()                                           
                        
                        
                    elif descriptors[index_descript][0] == '1': 
                        # Replication operator
                        print('* REPETITIONS *')
                        blocs_repetes = int(descriptors[index_descript].split('-')[1])
                        nbits_decal = descri(descriptors[index_descript+1], not(fin_affichage) and affiche_descriptors)['Data_width_bits']
                        nb_repetitions = reader.readbits(nbits_decal)
                        print('   number of descriptors replicated ', str(blocs_repetes), ' and number of replications = ', str(nb_repetitions))                        
                        descriptors = descriptors[:index_descript] + descriptors[index_descript+2: index_descript+2+blocs_repetes]*nb_repetitions + descriptors[index_descript+2+blocs_repetes:]
                        index_descript -= 1                               
                            
                    index_descript += 1
                    compte += 1        

                datas_messages += [datas_total]
                
                
                print(" ** END OF DATAS **")           
                    
                print('DATAS DESCRIPTORS NUMBER', len(datas_total))
                print('DATAS :')
                for key, value in datas_total.items():                     
                    if len(value) < 10:
                        # print values only for descriptors with few values
                        print(' ', key, ' : ', value, ' (', datas_unites[key] if key in datas_unites else '', ')')
                    else:
                        # lot of values : print only the number of values
                        print(' ', key, ' ( ',  len(value), ' data'+'s'*(len(value)>1) +')' )                 
                
                x = reader.readbits(4*BYTES)
                try:
                    print(' (7777 =) ', bits2bytes(bin(x))) #, 'END OF BUFR MESSAGE ', bufr_number)                 
                except:
                    print('ERROR : end of file ?')
                    break
                        
                print(' ----------- END OF BUFR MESSAGE n°', bufr_number, ' -----------') 
                bufr_number += 1
                    
        print(' END OF FILE ')
        
    nb = len(datas_messages)
    if nb > 0:
        print(' datas_messages contains ', nb, ' message'+'s'*(nb>1), 'in dictionary form, ', 'from 0 to'*(nb>1), str(nb-1)*(nb>1), 'datas_message[0]'*(nb==1))
          

# # Functions Images

# In[45]:


def polar_coord(data_im, center, radius):
    # transform polar coordinates to cartesian (with azimut begin with the north and turn clockwise)
    data_rad = cv2.warpPolar(data_im, center=center, maxRadius=radius, dsize=(2*radius,2*radius),flags=cv2.WARP_INVERSE_MAP + cv2.WARP_POLAR_LINEAR)
    data_rad = cv2.rotate(data_rad, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return data_rad

def radar_transfo(data_im, row_im, col_im, func):
    radius = col_im
    center = (col_im, col_im)
    # apply transformation function
    f=np.vectorize(func)
    data_im = f(data_im)
    # change polar to cartesian coordinates
    data_rad = polar_coord(data_im, center, radius)
    return data_rad   

def radar_transfo_bruit(data_im, row_im, col_im, func, bruit):
    # same function as above, but with a 'bruit' parameter
    radius = col_im
    center = (col_im, col_im)
    # apply transformation function
    f=np.vectorize(func)
    data_im = f(data_im, bruit)    
    # change polar to cartesian coordinates
    data_rad = polar_coord(data_im, center, radius)
    return data_rad 

# datas already cartesian, just apply a function transformation
def radar_coord_reflSigma(data_im, row_im, col_im):
    data_rad = []
    for r in range(row_im):
        data_1 = []
        for c in range(col_im):
            data_1 += [reflSigma(data_im[r][c])]
        data_rad += [data_1]
    return data_rad

def radar_coord_adv(data_im, row_im, col_im):
    data_rad = []
    for r in range(row_im):
        data_1 = []
        for c in range(col_im):
            pix22x, pix22y = adv_4(int(data_im[r][c]))
            data_1 += [[adv(pix22x), adv(pix22y)]]
        data_rad += [data_1]
    return data_rad


# In[49]:


# PAM and PAG functions
def reflZ(pixel, bruiti): 
    if pixel == 0:
        return bruiti
    if pixel == 1:
        return bruiti + 3
    if pixel == 2:
        return -9
    if pixel <= 79:
        return pixel - 11
    return np.nan

def reflSigma(pixel): 
    if pixel == 0:
        return 0
    if pixel< 63:
        return pixel*0.25
    if pixel == 63:
        return 15.75
    return np.nan

def correl(pixel):
    if pixel == 0:
        return 0.31
    if pixel< 79:
        return 0.3+pixel/100 
    return np.nan    

def phidp(pixel):   
    if pixel< 360:
        return pixel    
    return np.nan

def adv(pixel):   
    if pixel <= 1:
        return -328
    if pixel <=65533:
        return pixel/100-328
    if pixel == 65534:
        return np.nan
    return 328

def refldiff(pixel):   
    if pixel <= 199:
        return -10+pixel/10    
    return np.nan

def vitvraipol(pixel):
    if pixel == 0:
        return -60
    if pixel <= 241:
        return -60+0.5*pixel
    return np.nan

def adv_4(pixel):
    # convert a 4 octets to a 2*2 octets
    oct = hex(pixel)
    return int(oct[:6],16), int('0x'+oct[6:],16)

def adv_norm(pixel):
    # return the norm of the advector
    if pixel[0] == np.nan:
        return np.nan
    else:
        return math.sqrt(pixel[0]**2 + pixel[1]**2)

# # PROGRAM FOR MOSAIQUE (or reflectivity of individual radar)

# In[29]:


# VARIABLES TO DECLARE

# bufr file to decode
DIR_PATH = r'C:\Users\thepe\Documents\Data_Analyse\Meteo_France_API'
FILE_NAME = 'T_IMFR27_C_LFPW_20240126080000.bufr.gz'
#FILE_NAME = 'T_IPSR51_C_LFPW_20240129132500.bufr.gz'
#FILE_NAME = 'T_IPSR42_C_LFPW_20240131074000.bufr.gz'
#FILE_NAME = 'T_IPSR92_C_LFPW_20240131080000.bufr.gz'
FILE_NAME = 'T_IPSR58_C_LFPW_20240202181500.bufr.gz'
FILE_NAME = 'T_IPSR63_C_LFPW_20240203141000.bufr.gz'
FILE_NAME = 'T_PAME63_C_LFPW_20240207103500.bufr'
