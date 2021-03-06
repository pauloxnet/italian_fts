#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
"""Dictionary cleanup tool.

This module assists into the conversion of a ISpell/MySpell dictionary for the
use as full-text search dictionary in PostgreSQL using the tsearch2 tool.
"""

# Copyright (C) 2007 by Daniele Varrazzo
# $Id$
__version__ = "$Revision$"[11:-2]

import re
import locale
import string
from operator import itemgetter

import psycopg2

def getRevision(filename):
    from subprocess import Popen, PIPE
    import cElementTree as et

    f = Popen(['svn', 'info', filename, '--xml'], stdout=PIPE).stdout
    tree = et.parse(f)
    return int(tree.find('entry').get('revision'))
    

class Dictionary(dict):
    """A language dictionary.

    A dictionary is implemented as... a `dict`. The keys are the words,
    the values are the flags if any, else `None`.
    """
    header = None
    """The dictionary comment, on the file head."""

    def load(self, f):
        if isinstance(f, basestring):
            f = open(f)
        self.clear()
        h = []
        for row in f:
            if row.startswith('/'):
                h.append(row)
                continue

            row = row.rstrip()
            if row == '':
                continue

            p = row.rstrip().split('/')
            if len(p) == 1:
                self[p[0]] = ''
            else:
                self[p[0]] = p[1]

        self.header = ''.join(h)

    def save(self, f):
        if isinstance(f, basestring):
            f = open(f, 'w')
        if self.header:
            f.write(self.header)

        ws = list(self.iterkeys())
        # Sort in correct order... but the original file is sorted in ASCII
        #ws.sort(cmp=lambda a,b: locale.strcoll(a.lower(), b.lower()))

        #for w in ws:
            #f.write(w)
            #flags = self[w]
            #if flags is not None:
                #f.write("/")
                #f.write(flags)
            #f.write('\n')

        o = []
        for w, fl in self.iteritems():
            if not fl:
                o.append(w)
            else:
                o.append("%s/%s" % (w,fl))

        o.sort()
        f.write("\n".join(o))
        f.write('\n')

    def update(self, other):
        """Add a dictionary to this dictionary.

        Add new words, merge existing flags.
        """
        for w, f in other.iteritems():
            if w not in self:
                self[w] = f
                continue

            if f:
                self[w] = ''.join(sorted(set((self[w] or '') + f)))

class Operation(object):
    """An operation to perform on a dictionary.
    """

    label = "Basic operation. To be subclassed."
    """A textual representation of the operation."""

    def __init__(self, label=None):
        self.label = label or self.__class__.__name__
        
    def run(self, dictionary):
        print self.label
        return self._run(dictionary)
    
    def _run(self, dictionary):
        raise NotImplementedError


class RemoveWords(Operation):
    """Remove all the words from a dictionary matching a predicate."""
    def __init__(self, predicate, **kwargs):
        super(RemoveWords, self).__init__(**kwargs)
        self.predicate = predicate

    def _run(self, dictionary):
        to_del = filter(self.predicate, dictionary)
        for k in to_del:
            del dictionary[k]

class DropFlag(Operation):
    """Remove a flag from all the words."""
    def __init__(self, flag, **kwargs):
        super(DropFlag, self).__init__(**kwargs)
        self.flag = flag

    def _run(self, dictionary):
        flag = self.flag
        for w,f in dictionary.iteritems():
            if f and flag in f:
                dictionary[w] = "".join(f.split(flag))

class RenameFlag(Operation):
    """Change a flag letter."""
    def __init__(self, flag_in, flag_out, **kwargs):
        super(RenameFlag, self).__init__(**kwargs)
        self.flag_in = flag_in
        self.flag_out = flag_out

    def _run(self, dictionary):
        flag_in = self.flag_in
        flag_out = self.flag_out
        for w,f in dictionary.iteritems():
            if f and flag_in in f:
                dictionary[w] = flag_out.join(f.split(flag_in))

class PassatoRemotoIrregolare(Operation):
    eccezioni = set([
        'assurgere', 'capovolgere', 'convergere', 'dirigere', 'divergere',
        'eleggere', 'erigere', 'esigere', 'frangere', 'fungere', 'indulgere',
        'prediligere', 'recingere', 'redigere', 'redirigere', 'ricingere',
        'ridirigere', 'rifrangere', 'sorreggere', 'succingere', 'transigere',
        'urgere'])

    def __init__(self, flag, **kwargs):
        super(PassatoRemotoIrregolare, self).__init__(**kwargs)
        self.flag = flag

    def _run(self, dictionary):
        for w,f in list(dictionary.iteritems()):
            if not f or 'B' not in f:
                continue

            if w.endswith("ggere") and w not in self.eccezioni:
                dictionary[w] = (dictionary[w] or '') + self.flag
                tema = w[:-5]
                for suf in ('ssi', 'sse', 'ssero'):
                    dictionary.pop(tema+suf, None)

            elif w.endswith("gere") and w not in self.eccezioni:
                dictionary[w] = (dictionary[w] or '') + self.flag
                tema = w[:-4]
                for suf in ('si', 'se', 'sero'):
                    dictionary.pop(tema+suf, None)

class RimuoviFemminileInPp(Operation):
    def _run(self, dictionary):
        for w,f in list(dictionary.iteritems()):
            if w.endswith('a') and f and 'Q' in f \
            and 'F' in (dictionary.get(w[:-1]+'o') or ''):
                del dictionary[w]

class UnisciAggettiviMaschileFemminile(Operation):
    """Unisci aggettivi presenti in doppia forma."""
    def _run(self, dictionary):
        keep = RimuoviVerbi.keep
        for w, f in list(dictionary.iteritems()):
            if not f or 'O' not in f:
                continue

            fw = w[:-1] + 'a'
            if 'Q' in (dictionary.get(fw) or ''):
                if w in keep['O'] or fw in keep['Q']: continue

                del dictionary[fw]
                dictionary[w] = f.replace('O', 'o')

class RimuoviFemminileParticipioPassato(Operation):
    """Non serve: si ottiene per produzione."""
    def _run(self, dictionary):
        keep = RimuoviVerbi.keep
        for w, f in list(dictionary.iteritems()):
            if not f or 'm' not in f:
                continue

            fw = w[:-1] + 'a'
            if 'Q' in (dictionary.get(fw) or ''):
                if fw in keep['Q']: continue

                del dictionary[fw]

class UnisciAggettivoInCio(Operation):
    """Non serve: si ottiene per produzione. Richiede modifica di /o"""
    def _run(self, dictionary):
        keep = RimuoviVerbi.keep
        for w, f in list(dictionary.iteritems()):
            if not f or 'n' not in f or not w.endswith('a'):
                continue

            mw = w[:-1] + 'o'
            mf = dictionary.get(mw) or ''
            if 'O' in mf:
                if mw in keep['O']: continue

                del dictionary[w]
                dictionary[mw] = mf.replace('O', 'o')

class UnisciMestieri(Operation):
    """Femminile in ..trice unito al maschile in ..tore"""
    def _run(self, dictionary):
        keep = RimuoviVerbi.keep
        for w, f in list(dictionary.iteritems()):
            if not f or 'S' not in f or not w.endswith('tore'):
                continue

            fw = w[:-3] + 'rice'
            if fw not in dictionary: continue
            mf = dictionary[fw] or ''
            assert mf == 'S', w
            if 'S' in mf:
                del dictionary[fw]
                dictionary[w] = f + 'f'

class EliminaQuErre(Operation):
    """La combinazione /Q /R � usata a volte al posto di /u sul maschile."""
    def _run(self, dictionary):
        keep = RimuoviVerbi.keep
        for w, f in list(dictionary.iteritems()):
            if not f or 'Q' not in f or 'R' not in f:
                continue
            mw = w[:-1] + 'o'
            if mw not in dictionary:
                continue

            mf = dictionary[mw] or ""
            assert f in ('QR', 'RQ'), w

            del dictionary[w]

            fnew = 'p'
            if fnew not in mf:
                dictionary[mw] = mf + fnew
            else:
                print mw

class UnisciParoleConiugazioni(Operation):
    def _run(self, dictionary):
        keep = Dictionary(); keep.load("non-verbi.dict")
        dictionary.update(keep)

        # Ora pensiamo ai plurali in e, che tipicamente sono a parte perch�
        # spesso non corrisponde a nessuna coniugazione.
        for w, f in keep.iteritems():
            if not f: continue

            print w,
            if 'Q' in f:
                if w[-2] in 'cg':
                    pl = w[:-1] + 'he'
                else:
                    pl = w[:-1] + 'e'

            elif 'o' in f:
                #[^GCI]O    > -O,E
                #[^GC]IO    > -O,E
                #[GC]IO    > -IO,E
                #[GC]O    > -O,HE
                if w[-2] not in ('cgi'):
                    pl = w[:-1] + 'e'
                elif w[-2] == 'i' and w[-3] not in ('cg'):
                    pl = w[:-1] + 'e'
                elif w[-2] == 'i':
                    pl = w[:-2] + 'e'
                else:
                    pl = w[:-1] + 'he'

            elif 'p' in f:
                if w[-2] in 'cg':
                    pl = w[:-1] + 'he'
                else:
                    pl = w[:-1] + 'e'

            elif 'n' in f:
                pl = w[:-2] + 'e'

            elif 'O' in f or 'S' in f or 'N' in f:
                continue

            else:
                assert False, "%s/%s" % (w, f)

            print pl

            if pl not in dictionary:
                continue

            if pl in ('sole','molle'): continue
            
            pf = dictionary[pl]
            assert not pf or 'B' in pf, "%s/%s" % (pl, pf)
            del dictionary[pl]

class UnisciIoIi(Operation):
    def _run(self, dictionary):
        for w, f in list(dictionary.iteritems()):
            if not w.endswith('io'): continue
            pl = w[:-2] + 'ii'
            if not pl in dictionary: continue

            assert not dictionary[pl]
            dictionary[w] = (f or '') + 'n'
            del dictionary[pl]

def dbRun(f, *args, **kwargs):
    cnn = psycopg2.connect(database='tstest')
    try:
        cur = cnn.cursor()
        try:
            return f(cur, *args, **kwargs)
        finally:
            cur.close()
    finally:
        cnn.close()

class RimuoviVerbi(Operation):
    """Rimuovi i verbi dal vocabolario!!!
    """
    # Eccezioni: da non rimuovere anche se appaiono coniugazioni. La chiave
    # � il flag che le 'tiene in vita'.
    keep = {
        # rimosso: usare il dizionario ``non-verbi.dict`` per questo compito.
    }

    def _run(self, dictionary):
        vflags = set('ABCztj�PVZ')  # flag che indicano verbi
        aflags = set('IvsagDEFGHmb')  # attributi che vanno solo sui verbi
        pflags = set('Jde')  # flag che indicano prefissi
        kflags = set('WY')  # flag che vanno su aggettivi, ecc, quindi
                            # sono da mantenere

        def f(cur):
            cur.execute(
                "SELECT coniugazione"
                " FROM coniugazione JOIN attributo_mydict USING (infinito)"
                " WHERE attributo = 'presente'"
                ";")

            return set(map(itemgetter(0), cur))

        cons = dbRun(f)

        dflags = vflags | aflags | pflags | kflags
        for w, f in list(dictionary.iteritems()):
            if w not in cons:
                continue
            f = (f and set(f) or set()) - dflags
            
            if not f:
                if w not in self.keep[None]:
                    del dictionary[w]
            else:
                for l in f:
                    if w in self.keep[l]:
                        dictionary[w] = ''.join(f)
                        break
                else:
                    del dictionary[w]
                
class UnisciMestieri2(Operation):
    """Femminile in ..trice unito al maschile in ..tore

    Su molti mestrieri maschili manca la 'S': questa operazione corregge anche
    quelli.
    """
    def _run(self, dictionary):
        keep = RimuoviVerbi.keep
        for w, f in list(dictionary.iteritems()):
            if not w.endswith('tore'):
                continue

            fw = w[:-3] + 'rice'
            if fw not in dictionary: continue
            ff = dictionary[fw] or ''
            assert ff == 'S', w

            f = f or ''
            if 'S' not in f:
                f += 'S'

            del dictionary[fw]
            dictionary[w] = f + 'f'

class UnisciAvverbi(Operation):
    def _run(self, dictionary):
        already_flagged = 0
        for w, f in list(dictionary.iteritems()):
            if w.endswith('amente'):
                flag = 'Y'
                aggs = [w[:-6] + 'o', w[:-5] + 'o']
            elif w.endswith('emente') or w.endswith('lmente'):
                flag = w.endswith("e") and 'Y' or 'y'
                aggs = [w[:-6] + 'o', w[:-5] + 'o', w[:-5] + 'e', w[:-5]]
            else:
                continue

            for agg in aggs:
                if agg in dictionary and agg[-1] in 'aeiou':
                    print agg, "->", w
                    if flag not in (dictionary[agg] or ''):
                        dictionary[agg] = (dictionary[agg] or '') + flag
                    else:
                        already_flagged += 1
                    del dictionary[w]
                    break

        print "already_flagged", already_flagged

class UnisciPlurali(Operation):
    """Unisci il plurale al suo singolare."""
    def _run(self, dictionary):
        for w, f in list(dictionary.iteritems()):
            if w.endswith('o'):
                flag = 'O'
                pll = [ w[:-1] + 'i', w[:-1] + 'hi']
            elif w.endswith('e'):
                flag = 'S'
                pll = [ w[:-1] + 'i', w[:-1] + 'hi']
            elif w.endswith('a'):
                flag = 'Q'
                pll = [ w[:-1] + 'e', w[:-1] + 'he']
            else:
                continue

            # pu� essere stato gi� rimosso
            if w not in dictionary:
                continue

            for pl in pll:
                if pl in dictionary:
                    print pl, '->', w
                    del dictionary[pl]
                    if flag not in f:
                        dictionary[w] += flag
                    break

class UnisciMaschileFemminile(Operation):
    """Unisci i maschili con /n ai femminili nel flag /p"""
    def _run(self, dictionary):
        for w, f in list(dictionary.iteritems()):
            if not (w.endswith('o') and len(w) > 1 and w[-2] != 'i'
                    and 'n' in f):
                continue
            fw = w[:-1] + 'a'
            if fw not in dictionary:
                continue

            ff = dictionary[fw]
            assert ff in ('', 'Q')

            del dictionary[fw]
            dictionary[w] = f.replace('n', 'p')

class RenameAffFlags(Operation):
    """Rename all the flags in an .aff file.

    New names must be provided as comment after the ``flag`` instruction.
    """
    def __init__(self, aff_file, label=None):
        super(RenameAffFlags, self).__init__(label=label)
        self.aff_file = aff_file

    def _run(self, dictionary):
        flags_map = {}
        rex = re.compile(r'^flag\s+([*]?)\\?(.):\s*#\s*(.)\s*$')
        
        rows = open(self.aff_file).readlines()
        for row in rows:
            m = rex.match(row)
            if m is not None:
                flags_map[m.group(2)] =m.group(3)

        assert flags_map
        oflags = set(flags_map)

        for w, f in list(dictionary.iteritems()):
            if not (set(f) & oflags):
                continue

            dictionary[w] = ''.join(sorted(flags_map.get(_, _) for _ in f))

        of = open(self.aff_file, 'w')
        for row in rows:
            m = rex.match(row)
            if m is not None:
                row = "flag %s%s:\n" % (m.group(1), m.group(3))
            of.write(row)

class RimuoviConiugazioni(Operation):
    def _run(self, dictionary):
        nv = Dictionary(); nv.load("non-verbi.dict")

        def getConiugazioni(cur):
            cur.execute("""
SELECT infinito FROM verbo
    UNION
SELECT DISTINCT (coniugazione) FROM coniugazione
    UNION
SELECT substring(attributo FROM 10) || infinito
FROM attributo_mydict
WHERE attributo LIKE 'prefisso\_%'
    UNION
SELECT DISTINCT (substring (attributo FROM 10) || coniugazione)
FROM attributo_mydict JOIN coniugazione USING (infinito)
WHERE attributo LIKE 'prefisso\_%'
;""")
            return set(map(itemgetter(0), cur))

        cons = dbRun(getConiugazioni)

        lower = set(string.lowercase)
        upper = set(string.uppercase)
        
        for w, f in sorted(dictionary.iteritems()):
            if w not in cons:
                continue

            if w in nv:
                dictionary[w] = ''.join(sorted(_ for _ in f if _ not in upper))
                continue

            del dictionary[w]

class UnisciVerbi(Operation):
    """Unisci i verbi dal file ``verbi.dict``.

    Il file ``verbi.aff`` va unito a mano.
    """
    def _run(self, dictionary):
        vdict = Dictionary(); vdict.load("verbi.dict")
        dictionary.update(vdict)

        # aggiungi i prefissi
        def fetchPrefissi(cur):
            cur.execute(
                "SELECT infinito, substring(attributo FROM 10) "
                "FROM attributo_mydict "
                "WHERE attributo LIKE 'prefisso\_%';")

            return cur.fetchall()

        pre2flag = {
            'ri': 'z',
            'stra': 'y',
            'pre': 'x',
            're': 'w',
        }

        for v, pre in dbRun(fetchPrefissi):
            dictionary[v] += pre2flag[pre]

class RimuoviProduzioni(Operation):
    """Rimuovi le produzioni che partono dai verbi."""
    def _run(self, dictionary):
        import affix
        aff = affix.parseIspellAff(open("italian.aff"))
        nv = Dictionary(); nv.load("non-verbi.dict")
        vaff = affix.parseIspellAff(open("verbi.aff"))
        for l in 'wxyz':
            vaff[l] = aff[l]
        vdict = Dictionary(); vdict.load("verbi.dict")

        prev = None
        for w, f in sorted(vdict.iteritems()):
            if not prev or prev[0] != w[0]:
                print w
                prev = w
            prods = vaff.apply(w, f)
            for prod in prods:
                if prod in dictionary and prod not in nv:
                    del dictionary[prod]

class SeparaMaschileFemminile(Operation):
    """Suddividi l'aggettivo in maschile e femminile"""
    def _run(self, dictionary):
        for w, f in sorted(dictionary.iteritems()):
            if 'f' not in f and 'g' not in f: continue

            f = set(f)
            if 'f' in f:
                f.remove('f')
                f.add('a')
            else:
                f.remove('g')
                f.add('b')

            f.add('f')

            dictionary[w] = ''.join(sorted(f))

class NoTroppiVerbi(Operation):
    """Troppi verbi rendono headline() lento?"""
    def _run(self, dw):
        import affix
        aw = affix.parseIspellAff(open("italian.aff.before-verbs"))
        #wall = {}
        #for w in dw:
            #wall[w] = aw.apply(w, dw[w])

        idw = {}
        for b,f in dw.iteritems():
            idw.setdefault(b,[]).append(b)
            for w in aw.apply(b, f):
                idw.setdefault(w,[]).append(b)

        dv = Dictionary()
        dv.load("italian-verbs.dict")
        av = affix.parseIspellAff(open("verbi.aff"))
        #vall = {}
        #for w in dv:
            #vall[w] = av.apply(w, dv[w])

        #sw = set(wall)
        #for w in wall:
            #sw.update(wall[w])

        #idw = {}
        #for k, ww in wall.iteritems():
            #for w in ww:
                #idw.setdefault(w,[]).append(k)
            #idw.setdefault(k,[]).append(k)
        
        #sv = set(vall)
        #for w in vall:
            #sv.update(vall[w])
        
        #idv = {}
        #for k, ww in vall.iteritems():
            #for w in ww:
                #idv.setdefault(w,[]).append(k)
            #idv.setdefault(k,[]).append(k)

        idv = {}
        for b,f in dv.iteritems():
            idv.setdefault(b,[]).append(b)
            for w in av.apply(b, f):
                idv.setdefault(w,[]).append(b)

        f = file("italian.ambiguta", "w")
        try:
            for w in (set(idv) & set(idw)):
                print >>f, "%20s %20s" % (idw[w], idv[w])
        finally:
            f.close()
        
        

#: The list of operation to perform.
#: The first item is the revision number after which the operation is not to
#: be performed. Other parameters are the callable to run and the positional
#: and 
processes = [
    (13, RemoveWords(label="Togli le parole contenenti un apostrofo.",
        predicate=lambda w: "'" in w)),
    (16, DropFlag(label="Rimuovi il flag T (prefisso accentato).",
        flag="T")),
    (16, DropFlag(label="Rimuovi il flag U (un, ciascun).",
        flag="U")),
    (16, DropFlag(label="Rimuovi il flag X (pronomi tronchi).",
        flag="X")),
    (16, DropFlag(label="Rimuovi il flag i (articolo L').",
        flag="i")),
    (16, DropFlag(label="Rimuovi il flag q (prefisso bell').",
        flag="q")),
    (16, DropFlag(label="Rimuovi il flag r (prefisso brav').",
        flag="r")),
    (16, DropFlag(label="Rimuovi il flag s (prefisso buon').",
        flag="s")),
    (16, DropFlag(label="Rimuovi il flag ^ (prefisso sant').",
        flag="^")),
    (17, RenameFlag(label="Unisci i flag D ed E (pronominali, riflessivi)",
        flag_in="E", flag_out="D")),
    (22, PassatoRemotoIrregolare(label="Aggiungi flag per p.r. 2a coniugazione"
                                       " (sconfiggere -> sconfissi)",
        flag='s')),
    (24, RimuoviFemminileInPp(label="Rimuovi sostantivi femminili se c'� un"
                                    "participio passato che li include.")),
    (33, RimuoviFemminileParticipioPassato()),
    (33, UnisciAggettiviMaschileFemminile()),
    (34, UnisciAggettivoInCio()),
#    (xx, RimuoviVerbi(label="Togli tutti i verbi!!!",)),
    (37, UnisciMestieri()),
    (39, EliminaQuErre()),
    (45, UnisciParoleConiugazioni()),
    (46, UnisciIoIi()),
    (47, UnisciMestieri2()),
    (49, UnisciAvverbi()),
    (50, UnisciPlurali()),
    (61, UnisciMaschileFemminile()),
    (69, RenameAffFlags("italian.aff")),
    (78, RimuoviConiugazioni()),
    (78, UnisciVerbi()),
    (105, SeparaMaschileFemminile()),
    (107, RimuoviProduzioni()),
    (124, NoTroppiVerbi()),
]

        #def getVerbWithAttr(cur, attr):
            #cur.execute("SELECT infinito FROM attributo_mydict "
                        #" WHERE attributo = %s;", (attr,))
            #return set(map(itemgetter(0), cur))

        #prefixed = {}
        #prefixed['x'] = dbRun(getVerbWithAttr('prefisso_pre'))
        #prefixed['y'] = dbRun(getVerbWithAttr('prefisso_stra'))
        #prefixed['z'] = dbRun(getVerbWithAttr('prefisso_ri'))

if __name__ == '__main__':
    d_name = 'italian-other.dict'
    locale.setlocale(locale.LC_ALL, 'it_IT')
    
    d_rev = getRevision(d_name)

    dct = Dictionary()
    print "loading"
    dct.load(d_name)
    
    for p_rev, proc in processes:
        if p_rev >= d_rev:
            proc.run(dct)

    print "saving"
    dct.save(d_name)
