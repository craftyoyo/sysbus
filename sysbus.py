#! /usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim:set ts=4 sw=4 et:

# René Devichi février 2016

import sys
import os
import re
import argparse
import pickle
import json
import pprint
from collections import *
import functools
import tempfile
import configparser
import datetime


##
# @brief règle un problème de sortie vers un fichier
if sys.stdout.encoding is None:
    reload(sys)
    sys.setdefaultencoding('utf-8')


##
# @brief fonction lambda pour afficher sur stderr
error = functools.partial(print, file=sys.stderr)


##
# @brief requests n'est pas dans la distrib standard de Python3, d'où le traitement spécifique
#        pour l'import de cette librairie
try:
    import requests
    import requests.utils
except ImportError as e:
    error("erreur:", e)
    error("Installez http://www.python-requests.org/ : pip3 install requests")
    sys.exit(2)


##
# @brief informations de connexion à la Livebox
URL_LIVEBOX = 'http://livebox.home/'
USER_LIVEBOX = 'admin'
PASSWORD_LIVEBOX = 'admin'


##
# @brief niveau de détail, -v pour l'augmenter
verbosity = 0


##
# @brief session requests et entêtes d'authentification
session = None
sah_headers = None


##
# @brief affiche un message de mise au point
#
# @param level niveau de détail
# @param args
#
# @return 
def debug(level, *args):
    if verbosity >= level:

        RED = '\033[91m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        LIGHT_PURPLE = '\033[94m'
        PURPLE = '\033[95m'
        END = '\033[0m'

        #print(*args, file=sys.stderr)

        if level <= 1: sys.stderr.write(YELLOW)
        elif level == 2: sys.stderr.write(PURPLE)
        else: sys.stderr.write(RED)

        sys.stderr.write(' '.join(args))
        sys.stderr.write(END)
        sys.stderr.write('\n')


##
# @brief écrit le fichier de configuration
#
# @return 
def write_conf(args):
    config = configparser.ConfigParser()
    config['main'] = {}
    config['main']['URL_LIVEBOX'] = URL_LIVEBOX 
    config['main']['USER_LIVEBOX'] = USER_LIVEBOX 
    config['main']['PASSWORD_LIVEBOX'] = PASSWORD_LIVEBOX 

    rc = os.path.expanduser("~") + "/" + ".sysbusrc"
    with open(rc, "w") as f:
        config.write(f)

    print("configuration écrite dans %s" % rc)
    print("     url = %s" % (URL_LIVEBOX))
    print("    user = %s" % (USER_LIVEBOX))
    print("password = %s" % (PASSWORD_LIVEBOX))


##
# @brief lit le fichier de configuration
#
# @return 
def load_conf():
    global USER_LIVEBOX, PASSWORD_LIVEBOX, URL_LIVEBOX

    rc = os.path.expanduser("~") + "/" + ".sysbusrc"
    debug(3, 'rc file', rc)
    config = configparser.ConfigParser()
    try:
        config.read(rc)
        URL_LIVEBOX = config['main']['URL_LIVEBOX']
        USER_LIVEBOX = config['main']['USER_LIVEBOX']
        PASSWORD_LIVEBOX = config['main']['PASSWORD_LIVEBOX']
    except:
        return False

    debug(2, "%s %s %s" % (USER_LIVEBOX, PASSWORD_LIVEBOX, URL_LIVEBOX))
    return True


##
# @brief charge la conf et sort s'il y a une erreur
#
# @return 
def check_conf():
    print("Le fichier ~/.sysbusrc n'a pas été trouvé. Il est nécessaire pour le fonctionnement du programme.")
    print("Utilisez l'option -config (avec éventuellement -url -user -password) pour le créer.")
    print("Exemple:")
    print("   sysbus.py -config -password=1234ABCD")
    sys.exit(2)
    

##
# @brief retourne le chemin du fichier de sauvegarde du cookie et contextID
#
# @return 
def state_file():
    return tempfile.gettempdir() + "/" + "sysbus_state"


##
# @brief authentification 
#  - essaie avec les données mémorisées (.cookie / .contextID)
#  - envoie la requête d'authentification
#
# @return True/False
def auth():
    global session, sah_headers

    debug(3, 'state file', state_file())

    for i in range(2):

        if os.path.exists(state_file()):
            debug(1, 'loading saved cookies')

            with open(state_file(), 'rb') as f:
                cookies = requests.utils.cookiejar_from_dict(pickle.load(f))
                
                session = requests.Session()
                session.cookies = cookies

                contextID = pickle.load(f)

        else:
            debug(1, "new session")
            session = requests.Session()

            auth = { 'username':USER_LIVEBOX, 'password':PASSWORD_LIVEBOX }
            debug(2, "auth with", auth)
            r = session.post(URL_LIVEBOX + 'authenticate', params=auth) 

            if not 'contextID' in r.json()['data']:
                error("auth error", str(r.text))
                break

            contextID = r.json()['data']['contextID']

            # sauve le cookie et le contextID
            debug(1, 'setting cookies')
            with open(state_file(), 'wb') as f:
                data = requests.utils.dict_from_cookiejar(session.cookies)
                pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)
                data = contextID
                pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)
            
        sah_headers = { 'X-Context':contextID,
                    'X-Prototype-Version':'1.7',
                    'Content-Type':'application/x-sah-ws-1-call+json; charset=UTF-8',
                    'Accept':'text/javascript' }

        r = session.post(URL_LIVEBOX + 'sysbus/Time:getTime', headers=sah_headers, data='{"parameters":{}}')
        if r.json()['result']['status'] == True:
            return True
        else:
            os.remove(state_file())

    error("authentification impossible")
    return False


##
# @brief requêtes sans authentification: crée la session et des headers par défaut
#
# @return 
def noauth():
    global session, sah_headers
    session = requests.Session()
    sah_headers = { 'X-Prototype-Version':'1.7',
                    'Content-Type':'application/x-sah-ws-1-call+json; charset=UTF-8',
                    'Accept':'text/javascript' }




##
# @brief envoie une requête sysbus à la Livebox
#
# @param chemin
# @param args
# @param get
#
# @return 
def requete(chemin, args=None, get=False, raw=False):

    # nettoie le chemin de la requête
    c = str.replace(chemin, ".", "/")
    if c[0] == "/":
        c = c[1:]
    if c[0:7] != "sysbus/":
        c = "sysbus/" + c

    if get:
        if args is None:
            c += "?_restDepth=-1"
        else:
            c += "?_restDepth="  + args

        debug(1, "requête: %s" % (c))
        t = session.get(URL_LIVEBOX + c, headers=sah_headers)
        t = t.content
        #t = b'[' + t.replace(b'}{', b'},{')+b']'

    else:
        # complète les paramètres de la requête
        parameters = { }
        if not args is None:
            for i in args:
                parameters[i] = args[i]

        data = { }
        data['parameters'] = parameters

        # envoie la requête avec les entêtes qui vont bien
        debug(1, "requête: %s with %s" % (c, str(data)))
        t = session.post(URL_LIVEBOX + c, headers=sah_headers, data=json.dumps(data))
        t = t.content

    # il y a un truc bien moisi dans le nom netbios de la Time Capsule
    # probable reliquat d'un bug dans le firmware de la TC ou de la Livebox
    t = t.replace(b'\xf0\x44\x6e\x22', b'aaaa')

    if raw == True:
        return t

    t = t.decode('utf-8', errors='replace')
    if get and t.find("}{"):
        debug(2, "listes json multiples")
        t = "[" + t.replace("}{", "},{") + "]"

    try:
        r = json.loads(t)
    except:
        error("erreur:", sys.exc_info()[0])
        error("mauvais json:", t)
        return

    apercu = str(r)
    if len(apercu) > 50:
        apercu = apercu[:50] + "..."
    debug(1, "réponse:", apercu)

    if not get and 'result' in r:
        if not 'errors' in r['result']:
            debug(1, "-------------------------")
            return r['result']
        else:
            error("erreur:", t)
            return None
    
    else:
        debug(1, "-------------------------")
        return r
    

##
# @brief envoie une requête sysbus et affiche le résultat
#
# @param chemin chemin de la requête
# @param args paramètres supplementaires
#
# @return 
def requete_print(chemin, args=None, get=False):
    #print(chemin, args)
    #return
    result = requete(chemin, args, get)
    if result:
        pprint.pprint(result)
    return result



##
# @brief affiche le modèle
#
# @param node
# @param level
#
# @return 
def model(node, level=0, file=sys.stdout):

    #...
    print = functools.partial(error, file=file)

    def print_functions(node, indent=''):
        for f in node["functions"]:
            aa = ""
            for a in f['arguments']:
                flag = ""
                if 'attributes' in a and 'mandatory' in a['attributes'] and a['attributes']['mandatory']:
                    pass
                else:
                    flag = "opt "
                if 'attributes' in a and 'out' in a['attributes'] and a['attributes']['out']:
                    flag = "out "
                aa += ", " + flag + a['name']
            print(indent + "function:", f['name'], "(" + aa[2:] + ")")

    def print_parameters(node, indent=''):
        if 'parameters' in node:
            for p in node['parameters']:
                print(indent + "parameter:  %-20s : %-10s = '%s'" % (p['name'], p['type'], p['value']))


    # si ce n'est pas un datamodel, on sort
    if not 'objectInfo' in node:
        pprint.pprint(node)
        return

    o = node['objectInfo']

    print("")
    print("=========================================== level", level)
    print("OBJECT NAME: '%s.%s'  (name: %s)" % (o['keyPath'], o['key'], o['name'] ))

    print_functions(node)
    print_parameters(node)

    for i in node:
        if i == "children":
            #print("has children...", len(node[i]))
            pass
        elif i == "objectInfo":
             pass
        elif i == "functions":
            pass
        elif i == "parameters":
            pass

        elif i == "--templateInfo":
            print("templateInfo:")
            pprint(node[i])
            sys.exit()

        elif i == "errors":
            for e in node["errors"]:
                print(e["error"],  e["info"], e["description"])
        elif i == "instances":
            print("-->", i, len(node[i]))
            if i == "instances" and len(node[i])>0:
                k = 0
                for j in node[i]:
                    k += 1

                    #assert(len(j['children']) == 0)
                    #assert(len(j['instances']) == 0)
                    #print(j)
                    #model(j, 99)

                    print("instance %d: '%s.%s' (name: %s)" % (k, j['objectInfo']['keyPath'], j['objectInfo']['key'], j['objectInfo']['name']))
                    #print("j=",j)
                    #print("oi=", j['objectInfo'])
                    print_functions(j, indent="    ")
                    print_parameters(j, indent="    ")
                    pass
        else:
            print("-->", i, len(node[i]))

    for c in node['children']:
        model(c, level + 1, file=file)




##
# @brief analyse le fichier scripts.js à la recherche de requêtes sysbus
#
# @return 
def scan_sysbus(args):

    if len(args) > 0:
        # lecture des fichiers passés en ligne de commandes
        s = ""
        for i in args:
            if os.path.exists(i):
                s += open(i).read()
                debug(1, "lecture de %s" % i)

    else:
        if os.path.exists("scripts.js"):
            # lecture scripts.js local
            s = open("scripts.js").read()
            debug(1, "lecture de %s" % "scripts.js")
        else:
            # lecture scripts.js sur la Livebox
            session = requests.Session()
            rep = session.get(URL_LIVEBOX + "scripts.js")
            s = rep.text
            session.close()
            debug(1, "lecture de %s" % (URL_LIVEBOX + "scripts.js"))

    e = re.findall(r'"/?(sysbus[./].*)"', s)
    objects = dict()
    for s in e:
        #print(s)
        i = s.find(':')
        if i >= 0:
            o = s[0:i]
            m = s[i+1:]
        else:
            o = s
            m = ""

        if m.find('"') >= 0:
            m = m[0:m.find('"')]

        o = re.sub('"(.*)"', r'<o>', o)
        o = re.sub(r'\/', r'.', o)

        if not o in objects: 
            objects[o] = set()
        objects[o].add(m)

    for i in sorted(objects):
        print(i, list( objects[i]))


##
# @brief crée l'arborescence des scripts javascript de la Livebox à partir de scripts.js
#
# @return 
def extract_files(args):

    if os.path.exists("scripts.js"):
        with open("scripts.js") as f:
            js = f.read()
            f.close()
    else:
        session = requests.Session()
        rep = session.get(URL_LIVEBOX + "scripts.js")
        js = rep.text
        session.close()

    t = []
    for i in re.finditer(r'\/\*jsdep.*\*\/', js):
        t.insert(0, i.start())

    print("extracting %d files" % len(t))

    trailing = ""
    j = None
    for i in t:
        s = js[i:j]
        name = re.search(r"(web/js.*) ", s).group(1)
        j = i
        if not os.path.isdir(os.path.dirname(name)):
            os.makedirs(os.path.dirname(name))
        with open(name, "w") as f:
            f.write(s)
            f.close()
        js = js[0:i]
        #trailing += "/* " + name + " */\n"

    # crée un fichier avec ce qu'il reste
    with open("web/js/MAIN.js", "w") as f:
        f.write(js)
        if trailing != "":
            f.write(trailing)
        f.close()


##
# @brief demande le module de gestion de graphviz.
# il y en a plusieurs, j'en ai choisi récent et qui fonctionne avec python3
#
# documentation:
#   http://www.graphviz.org/
#   http://graphviz.readthedocs.org/
#
# @return 
def load_graphviz():
    try:
        from graphviz import Digraph as dg
    except ImportError as e:
        error("erreur:", e)
        error("Installez https://github.com/xflr6/graphviz : pip3 install graphviz")
        sys.exit(2)
    return dg


##
# @brief inspiré de http://forum.eedomus.com/viewtopic.php?f=50&t=2914
#
# @param parser
#
# @return 
def add_singles(parser):

    cmds = [
        [ "wifistate", "", "sysbus.NMC.Wifi:get" ],
#        [ "lanstate", "", "sysbus.NeMo.Intf.lan:getMIBs" ],
#        [ "dslstate", "", "sysbus.NeMo.Intf.dsl0:getDSLStats" ],
#        [ "iplan", "", "sysbus.NeMo.Intf.lan:luckyAddrAddress" ],
#        [ "ipwan", "", "sysbus.NeMo.Intf.data:luckyAddrAddress" ],
        [ "phonestate", "", "sysbus.VoiceService.VoiceApplication:listTrunks" ],
        [ "tvstate", "", "sysbus.NMC.OrangeTV:getIPTVStatus" ],
        [ "wifion", "", [ "sysbus.NMC.Wifi:set", { "Enable":True, "Status":True } ] ],
        [ "wifioff", "", [ "sysbus.NMC.Wifi:set", { "Enable":False, "Status":False } ] ],
#        [ "macon", "", [ "sysbus.NeMo.Intf.wl0:setWLANConfig", {"mibs":{"wlanvap":{"wl0":{"MACFiltering":{"Mode":"WhiteList"}}}}} ] ],
#        [ "macoff", "", [ "sysbus.NeMo.Intf.wl0:setWLANConfig", {"mibs":{"wlanvap":{"wl0":{"MACFiltering":{"Mode":"Off"}}}}} ] ],
        [ "devices", "", "sysbus.Hosts:getDevices" ],
    ]

    for i in cmds:
        parser.add_argument('-' + i[0], help=i[1], dest='req_auth', action='store_const', const=i[2])

        
##
# @brief mes commandes
#
# @param parser
#
# @return 
def add_commands(parser):

    cmds = [
        [ "wpson", "active le (WPS) Wi-Fi Protected Setup",
                    [ "sysbus/NeMo/Intf/wl0:setWLANConfig", 
                      {"mibs":{"wlanvap":{"wl0":{"WPS":{"Enable":True}},"wl1":{"WPS":{"Enable":True}}}}} ] ],
        [ "wpsoff", "désactive le (WPS) Wi-Fi Protected Setup",
                    [ "sysbus/NeMo/Intf/wl0:setWLANConfig", 
                      {"mibs":{"wlanvap":{"wl0":{"WPS":{"Enable":False}},"wl1":{"WPS":{"Enable":False}}}}} ] ],
        [ "version", "affiche la version et détails de la Livebox",
                    [ "sysbus.DeviceInfo:get" ] ],
    ]

    for i in cmds:
        parser.add_argument('-' + i[0], help=i[1], dest='req_auth', action='store_const', const=i[2])


    def info_cmd(args):
        """ affiche des infos de la Livebox (adresses IP)"""

        result = requete("DeviceInfo:get")
        print("%20s : %s" % ("SoftwareVersion", result['status']['SoftwareVersion']))
        print("%20s : %s" % ("UpTime", str(datetime.timedelta(seconds=int(result['status']['UpTime'])))))
        print("%20s : %s" % ("ExternalIPAddress", result['status']['ExternalIPAddress']))

        #result = requete("Devices.Device.lan:getFirstParameter", { "parameter": "IPAddress" })
        #print("%20s : %s" % ("IPv4Address", result['status']))

        #result = requete("NMC.IPv6:get") 
        #print("%20s : %s" % ("IPv6Address", result['data']['IPv6Address']))

        result = requete("NMC:getWANStatus")
        print("%20s : %s" % ("IPv6DelegatedPrefix", result['data']['IPv6DelegatedPrefix']))
        print("%20s : %s" % ("IPv6Address", result['data']['IPv6Address']))

        #result = requete("sysbus.Time:getTime")
        #print("%20s : %s" % ("Time", result['data']['time']))

        result = requete("sysbus.VoiceService.VoiceApplication:listTrunks")
        for i in result['status']:
            for j in i['trunk_lines']:
                if j['enable'] == "Enabled":
                    print("%20s : %s" % ("directoryNumber", j['directoryNumber']))



    #
    def wifi_cmd(args):
        """ affiche les passphrases des réseaux Wi-Fi """
        r = requete("sysbus.NeMo.Intf.lan:getMIBs")
        for wl in r['status']['wlanvap']:
            c = r['status']['wlanvap'][wl]
            print(wl, c['BSSID'], c['SSID'], c['Security']['KeyPassPhrase'], c['Security']['ModeEnabled'])

    #
    def setname_cmd(args):
        if len(args) < 2:
            error("Usage: -setname MAC name [source [source ...]]")
            return
        mac = str.upper(args[0])
        name = args[1]
        print("set name", mac, name)
        if len(args) == 2:
            requete_print('sysbus.Devices.Device.' + mac + ':setName', {"name":name })
        else:
            for i in range(2, len(args)):
                requete_print('sysbus.Devices.Device.' + mac + ':setName', {"name":name, "source":args[i]})

    #
    def getdev_cmd(args):
        if len(args) == 1:
            mac = str.upper(args[0])
            requete_print('sysbus/Devices/Device/' + mac + ':get')
        else:
            error("Usage: %s -getdev MACAddress" % sys.argv[0])

    #
    def dhcp_cmd(args):
        """ affiche la table des DHCP statiques """
        requete_print("sysbus.DHCPv4.Server.Pool.default:getStaticLeases")

    #
    def adddhcp_cmd(args):
        """ ajoute une entrée DHCP statique """
        if len(args) == 2:
            mac = str.upper(args[0])
            name = args[1]
            print("set dhcp", mac, name)

            requete_print('sysbus/DHCPv4/Server/Pool/default:addStaticLease',
                {"MACAddress": mac ,"IPAddress":  name })
        else:
            error("Usage: %s -adddchp MACAddress IPAddress" % sys.argv[0])

    #
    def deldhcp_cmd(args):
        """ supprime une entrée DHCP statique """
        if len(args) >= 1:
            if args[0] == "all":
                leases = requete('sysbus.DHCPv4.Server.Pool.default:getStaticLeases')
                for lease in leases['status']:
                    mac = lease['MACAddress']
                    requete_print('sysbus/DHCPv4/Server/Pool/default:deleteStaticLease', {"MACAddress": mac})

            else:
                for i in args:
                    mac = str.upper(i)
                    print("del dhcp", mac)
                    requete_print('sysbus/DHCPv4/Server/Pool/default:deleteStaticLease', {"MACAddress": mac})
        else:
            error("Usage: %s -deldchp MACAddress..." % sys.argv[0])
        
    #
    def hosts_cmd(args):
        """ affiche la liste des hosts """
        r = requete("sysbus/Hosts:getDevices")
        if len(args) > 0:
            for i in range(0, len(args)):
                for host in r['status']:
                    if host['physAddress'] == args[i]:
                        pprint.pprint(host)
                    elif host['clientID'] == args[i]:
                        pprint.pprint(host)
                    elif host['ipAddress'] == args[i]:
                        pprint.pprint(host)
        else:
            #pprint.pprint(r['status'])
            for host in r['status']:
                actif = " " if host['active'] else "*"
                print("%-18s %-5s %c %-30s %s" % (host['physAddress'], host['layer2Interface'], actif, host['ipAddress'], host['hostName']))

    #
    def ipv6_cmd(args):
        """ liste les hosts avec une adresse IPv6 """
        r = requete("sysbus.Devices:get")
        for i in r['status']:
            a = "-"
            if 'IPv6Address' in i:
                for j in i['IPv6Address']:
                    if j['Scope'] != 'link':
                        a = j['Address']
            b = "-"
            if 'IPAddress' in i: b = i['IPAddress']
            if a == "-": continue
            print("%4s %-32s %-5s %-16s %s" % (i['Index'], i['Name'], i['Active'], b, a))

    #
    def model_cmd(args):
        """ interroge le datamodel de la Livebox: -model [ raw | depth ] """

        if len(args) == 1 and args[0] == "raw":
            r = requete('sysbus', get=True, raw=True)
            if not r is None:
                with open("model.json", "wb") as f:
                    f.write(r)
                    f.close()
                print("modèle écrit dans model.json")
            else:
                error("modèle non accessible")

        else:
            chemin = 'sysbus'
            if len(args)  >= 1:
                chemin += '.' + args[0]

            if len(args) >= 2:
                r = requete(chemin, args[1], get=True)
            else:
                r = requete(chemin, get=True)

            #pprint.pprint(r)
            #print(json.dumps(r))
            #print(type(r))
            if not r is None:
                for i in r:
                    model(i)


    #
    def MIBs_cmd(args):
        """ interroge les MIBs de NeMo.Intf: -MIBs [ nom [ mib ] | show | save | dump ] """

        '''  trouvé dans opensource.orange.com
- A <b>flag set</b> is a space separated list of flag names. Example: "enabled up".                                             
- A <b>flag expression</b> is a string in which flag names are combined with the logical operators &&, || and !.                    
  Subexpressions may be grouped with parentheses.                                                                                
  The empty string is also a valid flag expression and it evaluates to true by definition. Example: "enabled && up".             
- Starting at a given Intf, the network stack dependency graph can be traversed in different ways. There are six predefined      
  <b>traverse modes</b>:                                                                                                         
  - <b>this</b> consider only the starting Intf.                                                                                 
  - <b>down</b> consider the entire closure formed by recursively following the LLIntf references.                               
  - <b>up</b> consider the entire closure formed by recursively following the ULIntf referenes.                                  
  - <b>down exclusive</b> the same as down, but exclude the starting Intf.                                                       
  - <b>up exclusive</b> the same as up, but exclude the starting Intf.                                                           
  - <b>one level down</b> consider only direct LLIntfs.                                                                          
  - <b>one level up</b> consider only direct ULIntfs.                                                                            
  - <b>all</b> consider all Intfs.                                                                                              
  .                                                                                                                                 
  The resulting structured set of Intfs is called the <b>traverse tree</b>.                                                      
  Example: if you apply the traverse mode "down" on Intf eth1 which has LLIntfs swport1, swport2 and swport3,                    
  the traverse tree will consist of eth1, swport1, swport2 and swport3.                                                          
- Some data model functions accept a parameter and/or a function name as input argument. By extension, they may also accept a    
  <b>parameter spec</b> and/or <b>function spec</b> as input argument. A parameter/function spec is the concatentation of          
  the dot-separated key path relative to a NeMo Intf instance and the parameter/function name, separated by an extra dot.        
  Example: the parameter spec "ReqOption.3.Value" refers to the parameter Value held by the object NeMo.Intf.{i}.ReqOption.3.    
        '''


        if len(args) == 0:

            # récupère toutes les MIBs de toutes les interfaces
            r = requete('sysbus.NeMo.Intf.data:getMIBs', { "traverse": "all" })
            if r is None: return
            pprint.pprint(r) 
            
        else:

            if args[0] == "show":
                intf = set()
                r = requete("NeMo.Intf.lo:getIntfs", { "traverse": "all" })
                if not r is None:
                    for i in r['status']:
                        intf.add(i)

                mibs = set()
                r = requete('sysbus.NeMo.Intf.lo:getMIBs', { "traverse": "this" })
                if not r is None:
                    for i in r['status']:
                        mibs.add(i)

                print()
                print("MIBs (%d): %s" % (len(mibs), str(sorted(mibs))))
                print()
                print("Intf (%d): %s" % (len(intf), str(sorted(intf))))

            elif args[0] == "dump":

                # liste toutes les interfaces
                intf = set()
                r = requete("NeMo.Intf.lo:getIntfs", { "traverse": "all" })
                if not r is None:
                    for i in r['status']:
                        intf.add(i)

                if not os.path.isdir("mibs"):
                    os.makedirs("mibs")

                # dump les datamodels de chaque interface
                for i in intf:
                    r = requete('sysbus.NeMo.Intf.' + i, get=True)
                    if r is None: continue

                    # le modèle en json
                    with open("mibs/" + i + ".dict", "w") as f:
                        pprint.pprint(r, stream=f)
                        #json.dump(r, f, indent=4, separators=(',', ': '))
                        f.close()

                    # le modèle décodé
                    with open("mibs/" + i + ".model", "w") as f:
                        for j in r:
                            print("---------------------------------------------------------", file=f)
                            model(j, file=f)
                        f.close()

                # dump le contenu des MIBs par interface
                for i in intf:
                    r = requete('sysbus.NeMo.Intf.' + i + ':getMIBs', { "traverse": "this" })
                    if r is None: continue
                    with open("mibs/" + i + ".mib", "w") as f:
                        pprint.pprint(r, stream=f)
                        f.close()

            # sauve toutes les MIBs de toutes les interfaces dans un fichier
            elif args[0] == "save":
                r = requete('sysbus.NeMo.Intf.data:getMIBs', { "traverse": "all" })
                if r is None: return
                with open("MIBs_all", "w") as f:
                    pprint.pprint(r, stream=f)
                    f.close()
                print("MIBs écrites dans MIBs_all")

            else:
                if len(args) > 1:
                    r = requete('sysbus.NeMo.Intf.' + args[0] + ':getMIBs', { "traverse": "this", "mibs":args[1] })
                else:
                    r = requete('sysbus.NeMo.Intf.' + args[0] + ':getMIBs', { "traverse": "this" })
                if r is None: return
                pprint.pprint(r)


    # ajout la règle pour vpn sur le NAS, l'interface web de la Livebox empêche d'en mettre sur le port 1701
    def add1701_cmd(args):
        """ règle spéciale pour rajouter la règle de forwarding pour L2TP """
        if len(args) != 1:
            error("Usage: ...")
        else:
            print("ajout règle udp1701 pour l'adresse interne %s" % args[0])
            requete_print('sysbus.Firewall:setPortForwarding',
                            {"description":"udp1701",
                            "persistent":True,
                            "enable":True,
                            "protocol":"17",
                            "destinationIPAddress":args[0],
                            "internalPort":"1701",
                            "externalPort":"1701",
                            "origin":"webui",
                            "sourceInterface":"data",
                            "sourcePrefix":"",
                            "id":"udp1701"})

    def graph_cmd(args):

        # charge graphviz
        Digraph = load_graphviz()

        r = requete('NeMo.Intf.lo:getMIBs', { "traverse":"all", "mibs":"base" })
        if r is None: return
        if not 'status' in r or not 'base' in r['status']: return
        r = r['status']['base']

        dot = Digraph(name='NeMo.Intf', format='svg', engine='dot')

        dot.attr('node', fontname='Helvetica')
        #dot.attr('node', fontname='Times-Roman')

        for i, node in r.items():
            #dot.attr('node', tooltip=v['Flags'] if 'Flags' in v else '')
            if 'Enable' in node:
                if node['Enable'] == True:
                    dot.node(i, shape='box')
                else:
                    dot.node(i, shape='ellipse', color='lightgrey')
            else:
                dot.node(i, shape='box', color='lightgrey')

        for i, v in r.items():
            for j in v['LLIntf']:
                dot.edge(i, j)

        dot.render(filename="nemo_intf", view=True)


    ##
    # @brief affiche la topologie du réseau tel qu'il est vu par la Livebox
    #
    # @param args 'simple' pour ne pas afficher les détails
    #
    # @return 
    def topo_cmd(args):

        # charge graphviz
        Digraph = load_graphviz()

        r = requete("Devices.Device.HGW:topology")
        if r is None or not 'status' in r: return
        r = r['status']

        simpleTopo = args[0] == "simple" if len(args) > 0 else False
        
        dot = Digraph(name='Devices', format='svg', engine='dot')

        # oriente le graphe de gauche à droite
        # plutôt que de haut en bas
        dot.attr('graph', rankdir="LR")


        ##
        # @brief fonction récursive de création du graphe de topologie
        #
        # @param node
        #
        # @return 
        def traverse(node):
            key = node['Key'].replace(':', '_')

            dot.attr('node', shape="box")

            # éléments communs à tous les devices:
            communs = set([ 'Tags', 'DiscoverySource', 'Key', 'Alternative', 'Active', 'Index', 'LastConnection',
                            'Name', 'LastChanged', 'Names', 'DeviceType', 'Master', 'DeviceTypes' ])

            if simpleTopo:
                label = node['Name']
            else:

                label = ""
                for nom in ['Name', 'Index', 'DeviceType', 'LastConnection']:
                    if nom in node:
                        s = str(node[nom])
                        if s != "":
                            label += r"%s: %s\n" % (nom, s)
                label += r"\n"

                ignores = set(['ClientID', 'Ageing', 'IPAddressSource', 'VendorClassID' ])
                for i, v in node.items():
                    if i in communs: continue
                    if i in ignores: continue
                    if type(v) is list or str(v) == "":
                        continue
                    label += r"%s: %s\n" % (i, str(v))

            dot.node(key, label=label, color="black" if node['Active'] else "lightgrey" )

            if 'Children' in node:
                for j in node['Children']:
                    dot.edge(key, j['Key'].replace(':', '_'))
                    traverse(j)

        for i in r:
            traverse(i)

        dot.render(filename="devices", view=True)



    ################################################################################


    # utilise la réflexivité de Python pour ajouter automatiquement les commandes "xxx_cmd"
    #
    for cmd, func in locals().items():
        if cmd.endswith("_cmd") and callable(func):
            parser.add_argument('-' + cmd[:-4], help=str.strip(func.__doc__ or ""), dest='run_auth', action='store_const', const=func)


##
# @brief requête sybus avec paramètres optionnels
#
# @param sysbus
# @param args
#
# @return 
def par_defaut(sysbus, args, raw=False):

    # par défaut, affiche l'heure de la Livebox
    if sysbus is None:
        result = requete("sysbus.Time:getTime")
        if result:
            print("Livebox time: ", result['data']['time'])
        else:
            pass

    else:
        parameters = OrderedDict()
        for i in args:
            a = i.split("=", 1)
            parameters[a[0]] = a[1]

        # analyse une requête formulée comme les queries sur les NeMo.Intf.xxx :
        # 'NeMo.Intf.wl1.getParameters(name="NetDevIndex", flag="", traverse="down")'
        p = sysbus.find('(')
        if p >= 0 and sysbus[-1] == ')' and sysbus.find('.') > 0:
            i = sysbus.find(':')
            if i == -1 or i > p:
                # sépare le chemin des paramètres entre parenthèses
                t = sysbus[p + 1:-1]
                sysbus = sysbus[:p]

                # remplace le dernier . par : (séparation du chemin du nom de la fonction)
                p = sysbus.rfind('.')
                sysbus = sysbus[0:p] + ':' + sysbus[p+1:]

                # ajoute les arguments passés entre parenthèses
                for i in t.split(','):
                    if i.find('=') > 0:
                        a = i.strip().split('=', 1)
                        parameters[a[0]] = a[1].strip('"')

        # envoie la requête
        if raw:
            r = requete(sysbus, parameters, raw=True)
            r = r.decode('utf-8', errors='replace')
            sys.stdout.write(r)
        else:
            requete_print(sysbus, parameters)


##
# @brief fonction principale
#
# @return 
def main():
    global USER_LIVEBOX, PASSWORD_LIVEBOX, URL_LIVEBOX
    global verbosity

    parser = argparse.ArgumentParser(description='requêtes sysbus pour Livebox')

    parser.add_argument("-v", "--verbose", action="count", default=verbosity)

    parser.add_argument('-scan', help="analyse les requêtes sysbus dans scripts.js",
            dest='run', action='store_const',
            const=scan_sysbus)

    parser.add_argument('-files', help="extrait les scripts",
            dest='run', action='store_const',
            const=extract_files)

    parser.add_argument('-url', help="url de la Livebox")
    parser.add_argument('-user', help="user de la Livebox")
    parser.add_argument('-password', help="password de la Livebox")

    parser.add_argument('-config', help="écrit la configuration dans ~/.sysbusrc",
            dest='run', action='store_const',
            const=write_conf)

    parser.add_argument('-noauth', help="ne s'authentifie pas avant les requêtes", action='store_true', default=False)
    parser.add_argument('-raw', help="", action='store_true', default=False)

    add_singles(parser)
    add_commands(parser)

    # ajout des arguments génériques (chemin de la commande et paramètres)
    parser.add_argument('sysbus', help="requête", nargs='?')
    parser.add_argument('parameters', help="paramètres", nargs='*')

    args = parser.parse_args()

    verbosity = args.verbose
    load_conf()

    if args.url:
        URL_LIVEBOX = args.url
        if URL_LIVEBOX[-1] != "/": URL_LIVEBOX += "/"
    if args.user:
        USER_LIVEBOX = args.user
    if args.password:
        PASSWORD_LIVEBOX = args.password

    if args.run:
        a = args.parameters
        if not args.sysbus is None:
            a.insert(0, args.sysbus)
        args.run(a)

    else:
        if args.noauth: 
            noauth()
        else:
            if not auth():
                sys.exit(1)

        if args.run_auth:
            a = args.parameters
            if not args.sysbus is None:
                a.insert(0, args.sysbus)
            args.run_auth(a)

        elif args.req_auth:
            if type(args.req_auth) is str:
                requete_print(args.req_auth)
            elif len(args.req_auth) == 1:
                requete_print(args.req_auth[0])
            else:
                requete_print(args.req_auth[0], args.req_auth[1])

        else:
            par_defaut(args.sysbus, args.parameters, args.raw)


if __name__ == '__main__':
    main()