from django.views.decorators.csrf import csrf_exempt

from game.models import *
from game.vars import *

import math


import datetime
from django.utils import timezone

import json
from django.http import HttpResponse


import random
random.seed(datetime.datetime.now())


@csrf_exempt
def demanar_dades(request, **kwargs):
    user_id = kwargs.get('user_id', None)

    response_data={}
    jugant = "false"

    user = None
    try:
        # partida que juga aquest usuari
        user = User.objects.get(id=user_id)
    except:
        print "Usuari "+str(user_id)+" no existeix"

    # estat de la partida actual
    if user.partida.estat == "JUGANT":
        altres_users = user.partida.user_set.all().exclude(id=user_id).order_by('num_jugador')

        jugant = "true"

        date_now = timezone.now()
        #print(date_now)
        date_start = user.partida.data_inicialitzacio+datetime.timedelta(0, TEMPS_INICI_SEC)
        #print(date_start)

        # control resta
        temps = (date_start - date_now).total_seconds()
        #print temps*1000
        if temps > 0:
            response_data["temps_inici"] = temps*1000
            response_data["partida_en_joc"] = False
        else:
            response_data["temps_inici"] = 0
            response_data["partida_en_joc"] = True

        response_data["temps_ronda"] = TEMPS_RONDA
        response_data["temps_espera"] = TEMPS_ESPERA

        response_data["total_rondes"] = NUM_RONDES
        response_data["numero_ronda"] = 1
        response_data["diners_inici_ronda"] = user.diners_actuals
        response_data["num_jugador"] = user.num_jugador

        response_data["altres_jugadors"] = [(u.num_jugador, u.diners_inicials) for u in altres_users]

    response_data["jugant"] = jugant
    return HttpResponse(json.dumps(response_data),content_type="application/json")

@csrf_exempt
def enviar_accio(request, **kwargs):
    user_id = kwargs.get('user_id', None)
    num_ronda = kwargs.get('ronda_id', None)
    result = kwargs.get('result', None)

    # Update de les dades. Falta controlar si hi ha errors
    userronda = UserRonda.objects.filter(user_id=user_id, ronda__num_ronda=num_ronda).order_by('-id')

    if len(userronda) > 0:
        if userronda[0].seleccio is None:
            userronda[0].ha_seleccionat = True
            userronda[0].seleccio = int(result)
            userronda[0].temps_seleccio = timezone.now()
            userronda[0].save()

            userronda[0].user.num_seleccions = userronda[0].user.num_seleccions + 1
            userronda[0].user.save()

        response_data = {"saved":"ok"}
    else:
        response_data = {"saved":"error"}

    return HttpResponse(json.dumps(response_data),content_type="application/json")


def calculs_ronda(partida_activa, num_ronda):
    #Comprovacio que no calculem valors d'una partida marcada com acabada
    if partida_activa.estat == "ACABADA" or partida_activa.estat == "ACABADA_MANUAL":
        return

    temps_actual = timezone.now()

    #Comprovacio de que estem tancant la ronda actual, no una de anterior o posterior!!
    if num_ronda != partida_activa.ronda_actual:
        return

    print "TANCANT RONDA:", num_ronda

    partida_activa.ronda_actual = partida_activa.ronda_actual + 1
    partida_activa.data_fi_ronda = temps_actual + datetime.timedelta(seconds=TEMPS_ESPERA_SEC+TEMPS_RONDA_SEC)
    partida_activa.save()

    ronda_acabada = partida_activa.ronda_set.get(num_ronda=partida_activa.ronda_actual-1)

    bucket_final_ronda = 0

    #Calcular resultats dels usuaris de la ronda
    for ur in ronda_acabada.userronda_set.all():
        #Si l'usuari no ha seleccionat
        if not ur.ha_seleccionat:
            if ur.ronda.num_ronda == 1:
                ur.seleccio = 2
            else:
                ur_anterior = UserRonda.objects.filter(user=ur.user, ronda__num_ronda=ur.ronda.num_ronda-1).order_by('-id')[0]
                tmp = random.randint(0,9)
                if tmp==9:  # 10% probabilitat d'incrementar 1
                    ur.seleccio = ur_anterior.seleccio + 2
                elif tmp==8: # 10% probabilitat de decrementar 1
                    ur.seleccio = ur_anterior.seleccio - 2
                else:
                    ur.seleccio = ur_anterior.seleccio

            if ur.seleccio < 0: ur.seleccio = 0
            if ur.seleccio > 4: ur.seleccio = 4
            ur.save()

        #Controlem que no puguis gastar mes del que tens
        if ur.user.diners_actuals - ur.seleccio < 0:
            print "Estan gastant mes del que tens!!!"
            ur.seleccio = ur.user.diners_actuals
            ur.save()

        #Comptador de les seleccions de cada usuari
        #if (ur.ha_seleccionat):
        #    ur.user.num_seleccions = ur.user.num_seleccions + 1

        gastat = 0
        for userronda in UserRonda.objects.filter(user_id=ur.user, ronda__partida__id=partida_activa.id , seleccio__isnull=False):
            gastat = gastat + userronda.seleccio

        ur.user.diners_actuals = ur.user.diners_inicials - gastat
        ur.user.save()

        bucket_final_ronda = bucket_final_ronda + gastat

    ronda_acabada.bucket_final_ronda = 120 - bucket_final_ronda
    ronda_acabada.temps_final_ronda = temps_actual
    ronda_acabada.calculada = True
    ronda_acabada.save()

    #Mirem si s'ha acabat ja la partida
    if partida_activa.ronda_actual > partida_activa.num_rondes:
        #Guardam un boolea si la partida a superat objectiu
        if (ronda_acabada.bucket_final_ronda <= 0):
            partida_activa.objectiu_aconseguit = True

        #Calculam el guany finals dels jugadors
        for ur in ronda_acabada.userronda_set.all():
            if (partida_activa.objectiu_aconseguit and ur.user.num_seleccions >= 9):
                ur.user.guany_final = ur.user.diners_actuals
            else:
                if (partida_activa.guanyen_igualment and ur.user.num_seleccions >= 9):
                    ur.user.guany_final = ur.user.diners_actuals
                else:
                    ur.user.guany_final = 0

            ur.user.save()

        partida_activa.estat = "ACABADA"
        partida_activa.data_finalitzacio = timezone.now()
        partida_activa.save()

    #Sino preparem la seguent ronda per als usuaris
    else:

        ronda_seguent = partida_activa.ronda_set.get(num_ronda=partida_activa.ronda_actual)
        ronda_seguent.bucket_inici_ronda = 120 - bucket_final_ronda

        ronda_seguent.temps_inici_ronda = temps_actual + datetime.timedelta(seconds=TEMPS_ESPERA_SEC)

        ronda_seguent.save()



@csrf_exempt
def demanar_resultat(request, **kwargs):
    user_id = kwargs.get('user_id', None)
    num_ronda = kwargs.get('ronda_id', None)

    #Mirem si l'usuari esta jugant
    user_ronda = UserRonda.objects.filter(user_id=user_id, ronda__num_ronda=num_ronda).order_by('-id')
    if len(user_ronda) == 0:
        #L'usuari no esta jugant
        return HttpResponse(json.dumps({"correcte": False}), content_type="application/json")

    user_ronda = user_ronda[0]
    user = user_ronda.user
    partida_activa = user.partida

    #Si la ronda actual es igual o mes petita que la de l'usuari
    #Miro si ja haig de canviar cap a la seguent
    if partida_activa.ronda_actual == user_ronda.ronda.num_ronda:

        #Mirem si hem d'actualitzar les dades de la ronda actual
        temps_restant = (partida_activa.data_fi_ronda - timezone.now()).total_seconds()

        if temps_restant <= 0:
            calculs_ronda(partida_activa, partida_activa.ronda_actual)

        else:
            #Si no s'ha acabat el temps mirem si han respos tots ja
            num_players = User.objects.filter(partida=partida_activa, is_robot=False).count()
            num_respostes = UserRonda.objects.filter(seleccio__isnull=False, ronda__partida = partida_activa, ronda__num_ronda=num_ronda).count()

            if num_players == num_respostes and int(partida_activa.ronda_actual) == int(num_ronda):
                calculs_ronda(partida_activa, partida_activa.ronda_actual)


    #Mirem si ja li podem retornar les dades a l'usuari
    if partida_activa.estat != "JUGANT":
        print partida_activa.estat
        return HttpResponse(json.dumps({"correcte": True, "jugant": False}), content_type="application/json")

    if user_ronda.ronda.num_ronda < partida_activa.ronda_actual and user_ronda.ronda.calculada:
        #Tornem a llegir les dades del server (ToDo: Possiblement aixo no cal fer-ho)
        user_ronda = UserRonda.objects.filter(user_id=user_id, ronda__num_ronda=num_ronda).order_by('-id')[0]
        game_users = User.objects.filter(partida_id=partida_activa.id).order_by('num_jugador')

        user = user_ronda.user
        response_data = {
            "correcte": True, #Per confirmar que les dades son correctes
            "ronda_acabada": True,

            "jugant": True if partida_activa.estat == "JUGANT" else False,

            "has_elegit": user_ronda.ha_seleccionat,
            "contribucio": user_ronda.seleccio,
            "diners_inicials": user_ronda.user.diners_inicials,
            "id_user": user_ronda.user.id,
            "ids": [gu.id for gu in game_users],
            "contribucions_ronda": [ur.seleccio for ur in user_ronda.ronda.userronda_set.all().order_by('user__num_jugador')],
            "ha_seleccionat": [ur.ha_seleccionat for ur in user_ronda.ronda.userronda_set.all().order_by('user__num_jugador')],
            "contribucions_ronda_aggr": user_ronda.ronda.bucket_inici_ronda - user_ronda.ronda.bucket_final_ronda,
            "contribucions_partida": 120 - user_ronda.ronda.bucket_final_ronda,
            "numero_ronda": partida_activa.ronda_actual,
            "diners_inici_ronda": user.diners_actuals,
            "diners_actuals_all": [ur.user.diners_actuals for ur in user_ronda.ronda.userronda_set.all().order_by('user__num_jugador')],
            "diners_inicials_all": [ur.user.diners_inicials for ur in user_ronda.ronda.userronda_set.all().order_by('user__num_jugador')],
            #Mirar si s'ha tancat la partida actual o no
            "temps_restant": (partida_activa.data_fi_ronda - timezone.now()).total_seconds() - TEMPS_RONDA_SEC,
            "temps_canvi_imatge": TEMPS_ESPERA_SEC,
        }
        return HttpResponse(json.dumps(response_data), content_type="application/json")


    else:
        return HttpResponse(json.dumps({"ronda_acabada": False}), content_type="application/json")


###############################################################################################
################         WEBSERVICES RESULTATS FINAL JOC      #################################
###############################################################################################

@csrf_exempt
def demanar_resultat_partida(request, **kwargs):

    user_id = request.session['user'].id
    last_ronda = Ronda.objects.filter(partida_id=request.session['user'].partida_id).order_by('bucket_final_ronda')[0]
    game_users = User.objects.filter(partida_id=request.session['user'].partida_id).order_by('num_jugador')
    response_data = {
        "correcte": True,
        "user_id": user_id,
        "objectiu": 120,
        "pot": 120 - last_ronda.bucket_final_ronda,
        "ids": [gu.id for gu in game_users],
        "nicknames": [gu.nickname for gu in game_users],
        "diners_inicials": [gu.diners_inicials for gu in game_users],
        "contribucions": [gu.diners_inicials - gu.diners_actuals for gu in game_users],
        "guanyen_igualment": last_ronda.partida.guanyen_igualment
    }

    user_ronda_seleccio = []
    robot_seleccio = []
    for up in game_users:
        user_ronda =  UserRonda.objects.filter(user_id=up.id).order_by('ronda_id')
        user_ronda_seleccio.append([ur.seleccio for ur in user_ronda])
        robot_seleccio.append([ur.ha_seleccionat for ur in user_ronda])
    response_data["rondes"] = user_ronda_seleccio
    response_data["robot"] = robot_seleccio

    return HttpResponse(json.dumps(response_data), content_type="application/json")


###############################################################################################
###############################################################################################
################         WEBSERVICES ADMINISTRACIO      #######################################
###############################################################################################
###############################################################################################
@csrf_exempt
def usuaris_registrats(request, **kwargs):
    response_data = {}

    partida_activa = Partida.objects.filter(estat="REGISTRANT")
    if len(partida_activa) > 0:
        response_data['registrant'] = True

        partida_activa = partida_activa[0]

        all_users = []
        for usuari in User.objects.filter(partida=partida_activa):
            data_users = {"num_registre": usuari.id,
                           "nom": usuari.nickname,
                           "data_registre": usuari.data_registre.strftime("%a,  %d/%m/%Y - %H:%M:%S")}
            all_users.append(data_users)
        response_data['usuaris'] = all_users

    else:
        response_data['registrant'] = False

    return HttpResponse(json.dumps(response_data), content_type="application/json")


@csrf_exempt
def estat_partida(request, **kwargs):
    response_data = {'partides': []}

    for partida in Partida.objects.filter(estat="JUGANT"):

        #Info de la partida
        users = User.objects.filter(partida__num_partida = partida.num_partida)

        data = {'num_partida': partida.num_partida,
                'data_creacio': partida.data_creacio.strftime("%a,  %d/%m/%Y - %H:%M:%S"),
                'data_inici': partida.data_inicialitzacio.strftime("%a,  %d/%m/%Y - %H:%M:%S"),
                'guanyen_igualment': partida.guanyen_igualment,
                }

        # Mirem si hem d'de tancar la ronda actual
        temps_restant = (partida.data_fi_ronda - timezone.now()).total_seconds()
        if temps_restant <= 0 and partida.ronda_actual <= partida.num_rondes:
            calculs_ronda(partida, partida.ronda_actual)

        ronda_data = []
        for i in range(1,partida.ronda_actual+1):
            num_players = User.objects.filter(partida=partida).count()

            num_respostes = UserRonda.objects.filter(seleccio__isnull=False, ronda__partida = partida, ronda__num_ronda=i).count()
            ronda_data.append({"ronda": i, "num_respostes": num_respostes, "num_jugadors": num_players})

        data["ronda_data"] = ronda_data

        if partida.ronda_actual > partida.num_rondes:
            data['estat'] = "Se han jugado todas las rondas"

        elif partida.ronda_actual == 1:
            if temps_restant > TEMPS_RONDA_SEC:
                data['estat'] = "Partida empieza en: "+str(int(round(temps_restant-TEMPS_RONDA_SEC)))+"sec."

            else:
                data['estat'] = "Ronda 1 jugando: <BR /> Quedan "+str(int(math.ceil(temps_restant)))+ " secs"

        else:
            if temps_restant > TEMPS_RONDA_SEC:
                data['estat'] = "Ronda "+str(partida.ronda_actual-1)+" resultados: <BR /> Quedan "\
                                         +str(int(round(temps_restant-TEMPS_RONDA_SEC)))+" secs"

            else :
                data['estat'] = "Ronda "+str(partida.ronda_actual)+" jugando: <BR /> Quedan "\
                                         +str(int(math.ceil(temps_restant)))+ " secs"

        response_data['partides'].append(data)

    return HttpResponse(json.dumps(response_data), content_type="application/json")



@csrf_exempt
def tancar_ronda(request, **kwargs):

    response_data = {}
    num_partida = kwargs.get('num_partida', None)
    partida = Partida.objects.get(num_partida=num_partida)
    calculs_ronda(partida, partida.ronda_actual)

    response_data["correcte"] = False
    return HttpResponse(json.dumps(response_data), content_type="application/json")



@csrf_exempt
def tancar_partida(request, **kwargs):
    print kwargs.get('num_partida', None)

    response_data = {}
    num_partida = kwargs.get('num_partida', None)
    partida = Partida.objects.get(num_partida=num_partida)
    if partida.estat == "JUGANT":
        partida.estat = "ACABADA_MANUAL"
        partida.data_finalitzacio = timezone.now()
        partida.save()

    response_data["correcte"] = False
    return HttpResponse(json.dumps(response_data), content_type="application/json")


@csrf_exempt
def llistat_partides(request, **kwargs):

    response_data = {}

    all_partides = []
    for partida in Partida.objects.filter().order_by('-id')[:15]:

        users = User.objects.filter(partida__num_partida = partida.num_partida)
        #print(partida.data_finalitzacio)
        data_partida = {"num_partida": partida.num_partida,
                        "guanys": [up.val_abacus for up in users],
                        "guanyen_igualment": partida.guanyen_igualment,
                        "objectiu_aconseguit": partida.objectiu_aconseguit,
                        "data_creacio": partida.data_creacio.strftime("%a, %H:%M:%S"),
                        "data_finalitzacio": partida.data_finalitzacio.strftime("%a, %H:%M:%S") if partida.data_finalitzacio else '-',
                        "estat": partida.estat
        }

        all_partides.append(data_partida)

    response_data["partida"] = all_partides

    return HttpResponse(json.dumps(response_data), content_type="application/json")

@csrf_exempt
def stats_partida(request, **kwargs):

    response_data = {}

    all_partides = []

    for partida in Partida.objects.filter(estat="ACABADA").order_by('-id')[:100]:

        users = User.objects.filter(partida__num_partida = partida.num_partida)
        data_partida = {"num_partida": partida.num_partida,
                        "objectiu_aconseguit": partida.objectiu_aconseguit,
                        "guanyen_igualment": partida.guanyen_igualment,
                        "guanys": [up.val_abacus for up in users],
                        "diners_inicials": [up.diners_inicials for up in users],
                        "diners_contribuits": [up.diners_inicials - up.diners_actuals for up in users],
                        "estat": partida.estat}


        all_partides.append(data_partida)

    response_data["partida"] = all_partides

    return HttpResponse(json.dumps(response_data), content_type="application/json")

@csrf_exempt
def stats_partida_detail(request, **kwargs):

    num_partida = kwargs.get('num_partida', None)

    partida = Partida.objects.filter(num_partida=num_partida)[0]
    users_partida = User.objects.filter(partida_id=partida.id).order_by('num_jugador')

    if partida.data_finalitzacio is None: dc = '-'
    else: dc = partida.data_finalitzacio.strftime("%a,  %d/%m/%Y - %H:%M:%S")

    response_data = {
        "num_partida": num_partida,
        "estat_partida": partida.estat,
        "guanyen_igualment": partida.guanyen_igualment,
        "guanys": [up.guany_final for up in users_partida],
        "edad": [up.rang_edat for up in users_partida],
        "date_creacio": partida.data_creacio.strftime("%a,  %d/%m/%Y - %H:%M:%S"),
        "date_inici": partida.data_inicialitzacio.strftime("%a,  %d/%m/%Y - %H:%M:%S"),
        "date_final": dc,
        "user_ids": [up.id for up in users_partida],
        "nicknames": [up.nickname for up in users_partida],
        "diners_inicials": [up.diners_inicials for up in users_partida],
        "diners_contribuits": [up.diners_inicials - up.diners_actuals for up in users_partida],
        "diners_reals": "",
        "bots": [up.bots for up in users_partida],
        "guany_final": [up.guany_final for up in users_partida],



        "diners_total": [up.diners_total for up in users_partida],
        "val_abacus": [up.val_abacus for up in users_partida],
    }

    # Rondes de tots els users de la partida
    user_ronda_seleccio = []
    robot_seleccio = []
    for up in users_partida:
        user_ronda =  UserRonda.objects.filter(user_id=up.id).order_by('ronda_id')
        user_ronda_seleccio.append([ur.seleccio for ur in user_ronda])
        robot_seleccio.append([ur.ha_seleccionat for ur in user_ronda])
    response_data["rondes"] = user_ronda_seleccio
    response_data["robot"] = robot_seleccio

    return HttpResponse(json.dumps(response_data), content_type="application/json")

