import numpy as np
import seaborn as sns
import scipy
import matplotlib.pyplot as plt
import pandas as pd
import parselmouth as pm
from scipy.io.wavfile import read as read_wav
from parselmouth.praat import call
import pyaudio
import speech_recognition as sr
import pickle
from scipy.stats import linregress

# ===================================================================================================================#
#Gloval Vars
_SPECTOGRAM_COLOR = 'afmhot'
_COMPLIMENT_POOL = ['Nice Job So Far!','Keep it Up','You are on the right track!']
S_SCORE_MODEL  = None
SCALER         = None


with open('Models_and_Misc/Standard_Scaler.pkl','rb') as file:
    SCALER = pickle.load(file)

with open('Models_and_Misc/optimzed_XGB.pkl','rb') as file:
    S_SCORE_MODEL = pickle.load(file)


#Helper Functions

def draw_spectrogram(spectrogram,ax ,dynamic_range=70):
    X, Y = spectrogram.x_grid(), spectrogram.y_grid()
    sg_db = 10 * np.log10(spectrogram.values)
    ax.pcolormesh(X, Y, sg_db, vmin=sg_db.max() - dynamic_range, cmap=_SPECTOGRAM_COLOR)
    ax.set_ylim([spectrogram.ymin, spectrogram.ymax])
    ax.set_xlabel("time [s]")

def draw_intensity(intensity,ax):
    ax.plot(intensity.xs(), intensity.values.T, linewidth=3, color='w')
    ax.plot(intensity.xs(), intensity.values.T, linewidth=1)
    ax.axis('off')
    ax.set_ylim(0)
def draw_pitch(pitch,ax):
    pitch_values = pitch.selected_array['frequency']
    pitch_values[pitch_values==0] = np.nan
    ax.plot(pitch.xs(), pitch_values, 'o', markersize=5, color='w')
    ax.plot(pitch.xs(), pitch_values, 'o', markersize=2)
    ax.set_ylim(0, pitch.ceiling)
    ax.axis("off")

def draw_gui_soundgraph(pitch,snd,ax):
    pre_emphasized_snd = snd.copy()
    pre_emphasized_snd.pre_emphasize()
    pectrogram = pre_emphasized_snd.to_spectrogram(window_length=0.03, maximum_frequency=8000)
    intensity = snd.to_intensity()
    draw_spectrogram(pectrogram,ax)
    ax_tag = ax.twinx()
    draw_intensity(intensity,ax_tag)
    ax_tag_2 = ax.twinx()
    draw_pitch(pitch,ax_tag_2)
    ax_tag.set_xlim([snd.xmin, snd.xmax])
    ax.set_ylabel("[Hz]")
    return ax_tag,ax_tag_2

def calculate_sound_features(snd):
    # Calculate A Bulck of prrat features simmilar to what we saw in MIT's paper
    pitch = snd.to_pitch().selected_array['frequency']
    intensity = snd.to_intensity().values
    max_pitch = np.max(pitch)
    min_pitch = np.min(pitch)
    mean_pitch = np.mean(pitch)
    diffPitchMaxMean = max_pitch - mean_pitch
    intensityMean = np.mean(intensity)
    intensityMax = np.max(intensity)
    intensityMin = np.min(intensity)
    broad_pitch = call(snd, "To Pitch", 0.0, 50, 600)  # create a praat pitch object
    minF0 = call(broad_pitch, "Get minimum", 0, 0, "hertz", "Parabolic")  # get min pitch
    maxF0 = call(broad_pitch, "Get maximum", 0, 0, "hertz", "Parabolic")  # get max pitch
    floor = minF0 * 0.9
    ceiling = maxF0 * 1.1
    pitch = call(snd, "To Pitch", 0.0, floor, ceiling)  # create a praat pitch object
    duration = call(snd, "Get total duration")  # duration
    meanF0 = call(pitch, "Get mean", 0, 0, "hertz")  # get mean pitch
    stdevF0 = call(pitch, "Get standard deviation", 0, 0, "hertz")  # get standard deviation
    harmonicity = call(snd, "To Harmonicity (cc)", 0.01, minF0, 0.1, 1.0)
    hnr = call(harmonicity, "Get mean", 0, 0)
    pointProcess = call(snd, "To PointProcess (periodic, cc)", minF0, maxF0)
    localJitter = call(pointProcess, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
    if meanF0 > 170 and meanF0 < 300:
        max_formant = 5500
    elif meanF0 <= 170:
        max_formant = 5000
    elif meanF0 >= 300:
        max_formant = 8000

    formants = call(snd, "To Formant (burg)", 0.0025, 5, max_formant, 0.025, 50)
    numPoints = call(pointProcess, "Get number of points")
    f1_list = []
    f2_list = []
    f3_list = []
    f4_list = []
    for point in range(0, numPoints):
        point += 1
        t = call(pointProcess, "Get time from index", point)
        f1 = call(formants, "Get value at time", 1, t, 'Hertz', 'Linear')
        f2 = call(formants, "Get value at time", 2, t, 'Hertz', 'Linear')
        f3 = call(formants, "Get value at time", 3, t, 'Hertz', 'Linear')
        f4 = call(formants, "Get value at time", 4, t, 'Hertz', 'Linear')
        f1_list.append(f1)
        f2_list.append(f2)
        f3_list.append(f3)
        f4_list.append(f4)
        f1_list.append(f1)
        f2_list.append(f2)
        f3_list.append(f3)
        f4_list.append(f4)

    # return relvent to us feature *delete later those that have no use
    result_dict = {'intensityMax': intensityMax,
                   'intensityMin': intensityMin,
                   'intensityMean': intensityMean,
                   'PitchMax': max_pitch,
                   'PitchMin': min_pitch,
                   'PitchMean': mean_pitch,
                   'F1_STD': np.std(f1_list),
                   'F3_STD': np.std(f3_list),
                   'F2_STD_F1': np.std(f2_list) / np.std(f1_list)}
    return result_dict



#Suggestion Generation Backend Function
def get_score_and_suggestion(feature_set,_STARTING_SCORE,_SCORE_MEAN,_SCORE_STD):
    _c_input_vector = np.array(list(feature_set.values())[:-1])
    _c_input_vector = np.nan_to_num(_c_input_vector)
    _c_input_vector = SCALER.transform(_c_input_vector[None,:])
    current_score = S_SCORE_MODEL.predict(X=_c_input_vector)[0]

    # current_score = score at time (t) , _STARTING_SCORE = score at time (t-1)
    ALPHA = 1
    if _SCORE_MEAN!=0:
        if (current_score > _SCORE_MEAN+ALPHA*_SCORE_STD) or (current_score < _SCORE_MEAN-ALPHA*_SCORE_STD):
            current_score = _STARTING_SCORE + (current_score-_SCORE_MEAN)

                                   ### NOTE ###
    """
    *******************************************************************************
            I think we need to improve the scoring method- its not working well.. 
        
        When there are NO advices the score can go down (and it shouldn't) and vice verse -
         When there are some correction to do the score goes up and it shouldn't
    *******************************************************************************
    """


    # If there is any suggestion to be made then return it with the current score prediction
    advice = ""
    num = 1
    if (feature_set['intensityMax'])  >= 86:
         advice += str(num) + ') Please CALM DOWN and try again! \n'
         return advice, current_score

    if (feature_set['intensityMin'] - 35.219) / 1.61539 > 1.6:
        advice += str(num)+ ') Please speak calmly \n'
        num += 1

    if ( -0.6314 + 0.0167 * feature_set['intensityMax']) < 0.3:
        return 'Please speak louder or get closer to the microphone\n' + current_score


    if (feature_set['diffPitchMaxMean'] - 197.169447) / 42.695449 >= 0.443:
        advice += str(num)+ ') Please lower you tone: \n Unless you are asking a question, your INTONATION needs to go DOWN in the end of the sentence\n'
        num += 1



    #If there were no bad feature found give user a compliment
    if(num == 1):
        return _COMPLIMENT_POOL[np.random.randint(0,len(_COMPLIMENT_POOL),1)[0]], current_score

    return advice, current_score
    # Pitch may be related to high/low tone
    # High Intensity is related to strong emotions such as anger.
    # Intensity may be related to the loudness of the voice OR by the speaker distance from the microphone
#


######according to DT : ########
# intensityMin >= 1.6 is good
# pitch_quant <=-0.96 is good
# diffPitchMaxMean <= 0.443 is good

# Pitch may be related to high/low tone
    # High Intensity is related to strong emotions such as anger.
    # Intensity may be related to the loudness of the voice OR by the speaker distance from the microphone
    #
    # Rising Intonation means the pitch of the voice rises over time[↗];
    # Falling Intonation means that the pitch falls with time[↘];
    # Dipping  Intonation   falls and then  rises[↘↗];
    # Peaking   Intonation   rises and then falls[↗↘].
# ===================================================================================================================#