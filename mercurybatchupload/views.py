import logging
import json
from django.http import HttpResponse, HttpResponseRedirect
from rest_framework import views, viewsets, permissions, authentication, exceptions, status
from rest_framework.response import Response
from mercuryservices.serializers import *
from mercuryservices.models import *
from datetime import datetime as dt
import requests
from django.db.models.base import ObjectDoesNotExist
from numbers import Number
import time


logger = logging.getLogger(__name__)


#batch_upload_save: validation
class BatchUploadSave(views.APIView):
    #permission_classes = (permissions.IsAuthenticated,)
    
    def post(self, request):
        status = []
        data = []
        try:
            data = json.loads(request.body.decode('utf-8'))            
            bottle_name = ""
            for row in data:
                #validate sample id/bottle bar code
                is_valid,message,bottle_id,sample,volume_filtered = validateBottleBarCode(row)
                if is_valid == False:
                    status.append({"message": message,"success": "false"})                
                    continue
                #validate constituent type
                is_valid,message,constituent_id = validateConstituentType(row)            
                if is_valid == False:
                    status.append({"message": message,"success": "false"})                   
                    continue
                #validate constituent type
                is_valid,message,constituent_method_id = validateConstituentMethod(constituent_id,row)
                if is_valid == False:
                    status.append({"message": message,"success": "false"})                   
                    continue                
                #validate quality assurance
                is_valid,message,quality_assurance_id_array = validateQualityAssurance(row)
                if is_valid == False:
                    status.append({"message": message,"success": "false"})                   
                    continue
                is_valid,message = validateAnalyzedDate(row)
                if is_valid == False:
                    status.append({"message": message,"success": "false"})                   
                    continue
                #validate result
                is_valid,message,result_id,sediment_dry_weight,sample_mass_processed = validateResult(sample,constituent_id,row)
                if is_valid == False:
                    status.append({"message": message,"success": "false"})                   
                    continue

                #calculate the result
                display_value,reported_value, detection_flag, daily_detection_limit,qa_flags = evaluateResult(row,result_id)
                raw_value = row["raw_value"]            

                #get method id
                method_id = row["method_id"]  
                
                ###save the result###                                                           
                result_details = Result.objects.get(id=result_id)
                result_details.raw_value = float(raw_value)
                result_details.method_id = method_id
                
                #get and process the final_value
                result_details.final_value = float(display_value)
                result_details.final_value = processFinalValue(result_details.final_value,method_id,volume_filtered,sediment_dry_weight,sample_mass_processed)
                
                #calculate the report value
                method_detection_limit,significant_figures,decimal_places = getMethodType(method_id)   
                if(method_detection_limit is not None and result_details.final_value is not None and result_details.final_value < method_detection_limit):
                    result_details.report_value = method_detection_limit
                else:
                    result_details.report_value = result_details.final_value   
                
                result_details.detection_flag = DetectionFlag.objects.get(detection_flag=detection_flag)
                
                #daily detection limit
                result_details.raw_daily_detection_limit =  daily_detection_limit   
                result_details.final_daily_detection_limit =  processDailyDetectionLimit(daily_detection_limit,method_id,volume_filtered,sediment_dry_weight,sample_mass_processed)
                
                result_details.entry_date = time.strftime("%Y-%m-%d")
                try:
                    analysis_comment = row["analysis_comment"]
                    result_details.analysis_comment = analysis_comment  
                except:
                    analysis_comment = ""            
                try:
                    analyzed_date = row["analyzed_date"]
                    analyzed_date = dt.strptime(analyzed_date, "%m/%d/%Y")
                    result_details.analyzed_date = analyzed_date
                except:
                    analyzed_date = ""           
                result_details.save()
                #save quality assurance
                quality_assurance_id_array = quality_assurance_id_array + qa_flags
                for quality_assurance_id in quality_assurance_id_array:
                    QualityAssurance.objects.create(result_id=result_id, quality_assurance_id=quality_assurance_id)
                status.append({"success":"true","result_id":result_id})
        except BaseException as e:
            if isinstance(data, list) is False:
                e = "Expecting an array of results"                    
            status.append({"success":"false","message":str(e)})                       
                
        return HttpResponse(json.dumps(status), content_type='application/json')

def validateBottleBarCode(row):
    is_valid = False
    bottle_id = -1  
    volume_filtered = None
    message = ""
    sample = {}
    try:
        bottle_name = row["bottle_unique_name"]
    except KeyError:
        message = "'bottle_unique_name' is required"
        return (is_valid,message,bottle_id,sample,volume_filtered)
    
    try:
        bottle_details = Bottle.objects.get(bottle_unique_name=bottle_name)
    except ObjectDoesNotExist:
        message = "The bottle '"+bottle_name+"' does not exist"
        return (is_valid,message,bottle_id,sample,volume_filtered)
        
    #get bottle id    
    bottle_id = bottle_details.id
    
    #find the sample bottle id
    try:
        sample_bottle_details = SampleBottle.objects.get(bottle=bottle_id)
    except ObjectDoesNotExist:
        message = "The bottle "+bottle_name+" exists but was not found in the results table"
        return (is_valid,message,bottle_id,sample,volume_filtered)
    
    is_valid = True
    sample_bottle_id = sample_bottle_details.id
    sample = sample_bottle_details.sample
    volume_filtered = sample_bottle_details.volume_filtered
    
    return (is_valid,message,bottle_id,sample_bottle_id,volume_filtered)

def validateConstituentType(row):
    is_valid = False
    constituent_id = -1   
    message = ""
    try:
        constituent_type = row["constituent"]
    except KeyError:
        message = "'constituent' is required"
        return (is_valid,message,constituent_id)
    
    #get constituent id
    try:
        constituent_type_details = ConstituentType.objects.get(constituent=constituent_type)
    except ObjectDoesNotExist:
        message = "The constituent type '"+constituent_type+"' does not exist"
        return (is_valid,message,constituent_id)
        
    constituent_id = constituent_type_details.id
    is_valid = True
    return (is_valid,message,constituent_id)


def validateConstituentMethod(constituent_id,row):
    is_valid = False
    constituent_method_id = -1   
    message = ""
    constituent_type = row["constituent"]
    try:
        method = row["method_id"]
    except KeyError:
        message = "'method_id' is required"
        return (is_valid,message,constituent_method_id)
    
    if isinstance( method, int ) is False:
        message = "Expecting an int for method_id"
        return (is_valid,message,constituent_method_id)
    
    try:
        constituent_type_details = ConstituentMethod.objects.get(constituent_type=str(constituent_id),method_type=str(method))
    except ObjectDoesNotExist:
        message = "The method code '"+str(method)+"' is not allowed for the constituent '"+constituent_type+"'"
        return (is_valid,message,constituent_method_id)
        
    is_valid = True
    constituent_method_id = constituent_type_details.id
    return (is_valid,message,constituent_method_id)


def validateQualityAssurance(row):
    is_valid = False       
    message = ""
    quality_assurance_id_array = []
    try:
        quality_assurance_id_array = row["quality_assurance"]
        #check if it's an array
        if isinstance(quality_assurance_id_array, list) is False:
            message = "'quality_assurance' needs to be a list of values"                   
            return (is_valid,message,quality_assurance_id_array)    
    except KeyError:
        is_valid = True
        
    #check that the given quality assurance exists
    for quality_assurance in quality_assurance_id_array:
        try:
            quality_assurance_type_details = QualityAssuranceType.objects.get(quality_assurance=quality_assurance)
        except ObjectDoesNotExist:
            message = "The quality assurance type '"+quality_assurance+"' does not exist"
            return (is_valid,message,quality_assurance_id_array)

        quality_assurance_id = quality_assurance_type_details.id
        quality_assurance_id_array.append(quality_assurance_id)        
        
    is_valid = True
    return (is_valid,message,quality_assurance_id_array)

def validateAnalyzedDate(row):
    #get the date
    try:
        analyzed_date = row["analyzed_date"]        
    except:
        analyzed_date = None
        
    if analyzed_date is None:
        is_valid = True
        return (is_valid,"")
    else:
        try:
            analyzed_date = dt.strptime(analyzed_date, "%m/%d/%Y")
            is_valid = True
            return (is_valid,"")
        except:
            is_valid = False
            return (is_valid,"The analyzed_date '"+str(analyzed_date)+"' does not match the format mm/dd/YYYY. For eg. 2/02/2014.")

def validateResult(sample_bottle_id,constituent_id,row):
    is_valid = False
    result_id = -1   
    message = ""
    bottle_name = row["bottle_unique_name"]
    constituent_type = row["constituent"]
    sediment_dry_weight = None
    sample_mass_processed = None
    result_details = {}
    #get isotope flag
    try:
        isotope_flag_id = row["isotope_flag_id"]
        #make sure that it is numeric
        if isinstance(isotope_flag_id, Number) is False:
            message = "Expecting a numeric value for isotope_flag_id"
            return (is_valid,message,result_id,sediment_dry_weight,sample_mass_processed)
    except KeyError:
        isotope_flag_id = None
    
    #make sure that a result is given
    try:
        raw_value = row["raw_value"]
        #make sure that it is numeric
        if isinstance(raw_value, Number) is False:
            message = "Expecting a numeric value for result"
            return (is_valid,message,result_id,sediment_dry_weight,sample_mass_processed)
    except KeyError:
        message = "'raw_value' is required"
        return (is_valid,message,result_id,sediment_dry_weight,sample_mass_processed)
    
    #Find the matching record in the Results table, using the unique combination of barcode + constituent { + isotope}        
    try:            
        if isotope_flag_id is None:
            result_details = Result.objects.get(constituent=str(constituent_id),sample_bottle=str(sample_bottle_id))
        else:
            result_details = Result.objects.get(constituent=str(constituent_id),sample_bottle=str(sample_bottle_id),isotope_flag=isotope_flag_id)
    except ObjectDoesNotExist:            
        if isotope_flag_id is None:
            message = "There is no matching record in the result table for bottle  '"+str(bottle_name)+"' and constituent type '"+str(constituent_type)
        else:
            message = "There is no matching record in the result table for bottle  '"+str(bottle_name)+"', constituent type '"+str(constituent_type)+"' and isotope flag '"+str(isotope_flag_id)+"'"
        return (is_valid,message,result_id,sediment_dry_weight,sample_mass_processed)
    
    #check if final value already exists
    final_value = result_details.final_value
    if final_value is not None:
        #print(result_details.id)
        message = "This result row cannot be updated as a final value already exists"
        return (is_valid,message,result_id,sediment_dry_weight,sample_mass_processed)
    
    is_valid = True
    result_id = result_details.id
    sediment_dry_weight = result_details.sediment_dry_weight
    sample_mass_processed = result_details.sample_mass_processed
    return (is_valid,message,result_id,sediment_dry_weight,sample_mass_processed)

#calculations
def evaluateResult(row,result_id):
    qa_flags = []
    #check if it is an archived sample
    raw_value = row["raw_value"]
    try:
        daily_detection_limit = row["daily_detection_limit"]
    except KeyError:
        daily_detection_limit = None
    if raw_value == -888:
        display_value,reported_value,detection_flag,daily_detection_limit,qa_flags = getArchivedSampleResult()
    #check if lost sample
    elif raw_value == -999:
        display_value,reported_value,detection_flag,daily_detection_limit,qa_flags = getLostSampleResult(raw_value,daily_detection_limit)
    else:
        #get isotope flag
        result_details = Result.objects.get(id=result_id)
        isotope_flag = str(result_details.isotope_flag)
        
        try:
            analysis_date = dt.strptime(row["analyzed_date"], "%m/%d/%Y")
        except:
            analysis_date = None
        constituent_type = row["constituent"]
        method_code = row["method_id"]        
        if ((constituent_type in ['FMHG','FTHG','UMHG','UTHG']) or ((constituent_type in ['PTHG','PMHG']) and (analysis_date >= dt.strptime("01/01/2003", "%m/%d/%Y"))) or ((constituent_type in ['SMHG','STHG']) and (analysis_date >= dt.strptime("01/01/2004", "%m/%d/%Y"))) and method_code != 165 or (constituent_type in ['BMHG'] and method_code in [108,184])) and (isotope_flag == 'NA' or isotope_flag == 'A'):
            #evaluate according to MDL
            method_detection_limit,significant_figures,decimal_places = getMethodType(method_code)            
            if raw_value < method_detection_limit:
                display_value,reported_value,detection_flag,daily_detection_limit,qa_flags = evaluateResultByMDL(daily_detection_limit,method_detection_limit)
            else:                
                #evaluate according to significant_figures & decimal_places
                display_value,reported_value,detection_flag,daily_detection_limit,qa_flags = evaluateResultBySigfigsDecimals(raw_value,daily_detection_limit,method_detection_limit,significant_figures,decimal_places)
        elif ((isotope_flag == 'NA' or isotope_flag == 'A') and ((constituent_type in ['BMHG'] and method_code != 108 ) or (constituent_type in ['BTHG']) or (constituent_type in ['DMHG','DTHG','STHG','PMHG','PTHG','SMHG','SRHG']))) or (isotope_flag in ['X-198','X-199','X-200','X-201','X-202']):
            #set DDL to -999 for DTHG because it does not have a DDL  
            if constituent_type == 'DTHG':
                daily_detection_limit = -999
            #set MDL to DDL  
            method_detection_limit = daily_detection_limit
            #all isotopes should use a decplaces of 3 despite what is in the
            if isotope_flag in ['X-198','X-199','X-200','X-201','X-202']:
                decimal_places = 3            
            method_detection_limit,significant_figures,decimal_places = getMethodType(method_code)            
            if raw_value < method_detection_limit:
                #evaluate according to MDL
                display_value,reported_value,detection_flag,daily_detection_limit,qa_flags = evaluateResultByMDL(daily_detection_limit,method_detection_limit)
            else:
                #evaluate according to significant_figures & decimal_places
                display_value,reported_value,detection_flag,daily_detection_limit,qa_flags = evaluateResultBySigfigsDecimals(raw_value,daily_detection_limit,method_detection_limit,significant_figures,decimal_places)
        else:
            if raw_value < 1:        
                display_value = '0'+ str(raw_value)
            else:
                display_value = str(raw_value)
            detection_flag = 'NONE'
            reported_value = display_value
    return (display_value,reported_value, detection_flag, daily_detection_limit,qa_flags)


#Archived Sample
#A value of -888 indicates an archived sample  
#an archived sample is one for which no near-term analysis is expected  
#in order to not leave a "hole", a value of -888 is used  
#VALUE should remain -888  
#REPORTED_VALUE and DISPLAY_VALUE should be -888  
#DETECTION_FLAG should be 'A'  
#DAILY_DETECTION_LIMIT should be set to -888  
#No QA flag for the result  
def getArchivedSampleResult():
    qa_flags = []
    reported_value = -888
    display_value = str(-888)
    detection_flag = 'A'
    daily_detection_limit = -888
    return (display_value,reported_value, detection_flag, daily_detection_limit,qa_flags)

#Lost Sample
#A value of -999 indicates a lost sample  
#VALUE should remain -999  
#REPORTED_VALUE and DISPLAY_VALUE should be -999  
#DETECTION_FLAG should be 'L'  
#DAILY_DETECTION_LIMIT should be set to -999 if not otherwise provided  
#Separately, a QA flag of LS should be added for the result  
#but that should be accomplished by the batch load process, not this trigger 
def getLostSampleResult(raw_value,daily_detection_limit):
    if daily_detection_limit == None:
        daily_detection_limit = -999
    elif(daily_detection_limit == -888): 
        daily_detection_limit = -999
    reported_value = raw_value
    detection_flag = 'L'
    display_value = str(raw_value)
    qa_flags = [] 
    qa_flag_id = QualityAssuranceType.objects.get(quality_assurance='LS')
    qa_flags.append(qa_flag_id)
    return (display_value,reported_value, detection_flag, daily_detection_limit,qa_flags)

def evaluateResultByMDL(daily_detection_limit,method_detection_limit):   
    if method_detection_limit < 1:
        #add leading zero
        display_value = '0'+ chr(method_detection_limit)
    else:
        display_value = char(method_detection_limit)
    reported_value = method_detection_limit
    detection_flag = '<'
    return (display_value,reported_value, detection_flag, daily_detection_limit,[])
    
def evaluateResultBySigfigsDecimals(raw_value,daily_detection_limit,method_detection_limit,significant_figures,decimal_places): 
    num_infront,num_behind,is_decimal_exists = getDecimalInfo(raw_value)    
    
    if num_infront >= significant_figures+1:
        sigfig_value = truncFloat(raw_value,significant_figures+1-num_infront)
    elif num_behind == 0:
        sigfig_value = raw_value
    elif num_infront == 0:
        sigfig_value = truncFloat(raw_value,decimal_places+1)
    elif (num_infront+num_behind) == significant_figures+1:
        sigfig_value = truncFloat(raw_value,num_behind)
    elif (num_infront+num_behind) != significant_figures+1:
        sigfig_value = truncFloat(raw_value,(num_behind - ((num_infront + num_behind) - (significant_figures + 1))))
    else:
        sigfig_value = raw_value
        
    #pad sigfig_value with zeroes
    sigfig_value_str = padValue(sigfig_value,significant_figures+1,decimal_places+1)
    rounded_val = roundByRuleOf5(sigfig_value, sigfig_value_str,significant_figures,decimal_places)    
    #if the daily_detection_limit is null, assign the MDL  
    if daily_detection_limit == None:        
        daily_detection_limit = method_detection_limit
    #set the reported value to the value     
    reported_value = rounded_val
    #determine the reported value and detection flag according to the DDL  
    #if the value is greater than the MDL and less than the DDL (MDL < VALUE < DDL),  
    #set the reported value to the value and the flag to E  
    if rounded_val >= method_detection_limit and rounded_val < daily_detection_limit:            
        detection_flag = 'E'
    #if the value is greater than the MDL and greater than the DDL (MDL < VALUE and DDL < VALUE),  
    #set the reported value to the value and the flag to NONE  
    elif rounded_val >= method_detection_limit and rounded_val >= daily_detection_limit:
        detection_flag = 'NONE'
    else:
        detection_flag = 'NONE'
    #Determine the display value by padding with trailing zeros if necessary  
    #Pad the reported_value with trailing zeros if length < sigfigs + 1 (and decimal point)
    display_value_str = padValue(reported_value,significant_figures,decimal_places)
    #pad a leading zero if the value is less than 1  
    if reported_value < 1 and reported_value > 0:
        display_value_str = '0'+display_value_str
        
    return (display_value_str,reported_value, detection_flag, daily_detection_limit,[])

def padValue(value,significant_figures,decimal_places):
    num_infront,num_behind,is_decimal_exists = getDecimalInfo(value)
    value_str = str(value)
    counter = len(value_str) 
    #if decimal exists
    if(num_behind > 0):
        if value >= 1:                         
            num_padding = significant_figures+1-counter
            if (len(value_str) != significant_figures+1):                
                value_str = addPadding(num_padding,value_str)
        else:            
            num_padding = decimal_places+1-counter
            if (len(value_str) != decimal_places+1):            
                value_str = addPadding(num_padding,value_str)
    return value_str
                 
def addPadding(num_padding,value_str):
    counter = len(value_str)            
    #if num_padding == 0:
    # do nothing
    if num_padding > 0:
        for x in range(1, num_padding):
            value_str = value_str+"0"
    return value_str

def roundByRuleOf5(sigfig_value, sigfig_value_str,significant_figures,decimal_places):
    if sigfig_value >= 1:
        rounded_val = getRoundedVal(sigfig_value, sigfig_value_str,significant_figures)
    else:
        rounded_val = getRoundedVal(sigfig_value, sigfig_value_str,decimal_places)
    return rounded_val
            
def getRoundedVal(sigfig_value, sigfig_value_str,value):
    num_infront,num_behind,is_decimal_exists = getDecimalInfo(sigfig_value)
    is_last_digit_five,is_last_digit_zero = getSigfigInfo(sigfig_value_str)
    ndigits = num_behind-(num_infront+num_behind-value)
    #confirm that this is ok
    #if last digit is a (trailing) zero, do not do anything if no decimal place  
    if is_last_digit_zero and (is_decimal_exists):
        rounded_val = sigfig_value
    #if last digit is a (trailing) zero, round if there is a decimal place  
    #Or if last digit is not a 5 and there isn't a decimal place, round,-1 
    #Or if last digit is not a 5 and there is a decimal place, round,-1  
    elif (is_last_digit_zero and not is_decimal_exists) or ((not is_last_digit_five) and (not is_decimal_exists)) or ((not is_last_digit_five) and is_decimal_exists):
        rounded_val = round(sigfig_value,ndigits)
    #if last digit is a 5 round off or up based on 2nd last digit 
    elif is_last_digit_five:
        digit_before_last = getDigitBeforeLast(sigfig_value_str,num_behind)
        #if last digit is a 5 and second to last digit is even, trunc  
        if digit_before_last%2 == 0:
            rounded_val = truncFloat(sigfig_value,ndigits)
        #if last digit is a 5 and second to last digit is odd, round 
        else:
            rounded_val = round(sigfig_value,ndigits)
    else:
        rounded_val = sigfig_value
    return rounded_val
        
def getDigitBeforeLast(value_str,num_behind):
    length = len(value_str)
    if(num_behind > 0) and num_behind == 1:
        #if decimal exists and the decimal point is in the second to last position, take the number just before the decimal point        
        digit_before_last = value_str[length-3:length-2]
    else:
        #else take the second to last digit  
        digit_before_last = value_str[length-2:length-1]
    return int(digit_before_last)
        
def getSigfigInfo(val):    
    is_last_digit_five = False
    is_last_digit_zero = False
    val_str = str(val)
    length = len(val_str)    
    last_digit = val_str[length-1:length]
    if last_digit == '5':
        is_last_digit_five = True
    elif last_digit == '0':
        is_last_digit_zero = True    
    return (is_last_digit_five,is_last_digit_zero)
            
def getDecimalInfo(val):
    str_val = str(val)
    val_arr = str_val.split(".")
    num_infront = len(val_arr[0])
    if len(val_arr) > 1:
        num_behind = len(val_arr[1])
        is_decimal_exists = True
    else:
        num_behind = 0
        is_decimal_exists = False
    if num_infront == 1 and val_arr[0]=='0':
        num_infront = 0
    
    return (num_infront,num_behind,is_decimal_exists)

def truncFloat( floatValue,  decimalPlaces ):
    return round(int(floatValue*pow(10,decimalPlaces))*pow(10,-decimalPlaces),decimalPlaces)

    
def getMethodType(method_code):    
    method_type_details = MethodType.objects.get(id=str(method_code))           
    significant_figures = method_type_details.significant_figures
    decimal_places = method_type_details.decimal_places
    if method_type_details.method_detection_limit is None or method_type_details.method_detection_limit == '':
        method_detection_limit = 0
    else:   
        method_detection_limit = float(method_type_details.method_detection_limit)
    return (method_detection_limit,significant_figures,decimal_places)

def processFinalValue(final_value, method_id,volume_filtered, sediment_dry_weight,sample_mass_processed):
    value = final_value
    if (method_id is None or final_value is None):
        value = final_value
    elif (final_value == -999 or final_value == -888):
        value = final_value
    elif (method_id == 86 or method_id == 92 or method_id == 103 or method_id == 104):
        value = round(final_value * 100, 2)
    elif (method_id == 42):
        value = round(final_value / 1000, 4)
    elif (method_id == 48 or method_id == 49 or method_id == 83	or method_id == 84 or method_id == 85 or method_id == 233 or method_id == 211):
        if (volumeFiltered is not None):
            value = round(final_value * 1000 / volumeFiltered, 3)
    elif (method_id == 52 or method_id == 71):
        if (sediment_dry_weight is not None and sediment_dry_weight != -999):
            if (sample_mass_processed is not None and sample_mass_processed != -999):
                value = round(final_value / sediment_dry_weight/ sample_mass_processed, 2)
    elif (method_id == 73 or method_id == 127 or method_id == 157 or method_id == 228):
        if (sample_mass_processed is not None and sample_mass_processed != -999):
            value = round(final_value / sample_mass_processed, 2)
    elif (method_id == 50 or method_id == 74 or method_id == 82):
        if (sediment_dry_weight is not None and sediment_dry_weight != -999):
            value = round(final_value / sediment_dry_weight, 2)
    return value

def processDailyDetectionLimit(daily_detection_limit, method_id,volume_filtered, sediment_dry_weight,sample_mass_processed):
    value = daily_detection_limit
    if (method_id is None or daily_detection_limit is None or daily_detection_limit == 0):
        value = daily_detection_limit
    elif (daily_detection_limit == -999):
        value = daily_detection_limit
    elif (method_id == 42):
        value = daily_detection_limit / 1000;
    elif (method_id == 48 or method_id == 49 or method_id == 83 or method_id == 84 or method_id == 85 or method_id == 233):
        if (volume_filtered is not None):
            value = daily_detection_limit * 1000 / volume_filtered			
    elif (method_id == 71 or method_id == 211):
        if (sediment_dry_weight is None or sediment_dry_weight == -999):
            value = -999
        else:
            if (sample_mass_processed is None or sample_mass_processed == -999):
                value = -999
            else:
                value = daily_detection_limit / sediment_dry_weight / sample_mass_processed;
    elif (method_id == 50 or method_id == 74 or method_id == 82):
        if (sediment_dry_weight is None or sediment_dry_weight == -999):
            value = -999
        else:
            value = daily_detection_limit / sediment_dry_weight;
    elif (method_id == 73 or method_id == 127 or  method_id == 157 or method_id == 228):
        if (sample_mass_processed is None or sample_mass_processed == -999):
            value = -999
        else:
            value = daily_detection_limit / sample_mass_processed;
    return value;
	