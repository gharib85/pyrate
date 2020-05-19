# -*- coding: utf-8 -*-
import os

from sympy.printing.pycode import PythonCodePrinter
from sympy import Abs, Mul, Symbol, conjugate

from Definitions import mSymbol, splitPow

from Logging import loggingCritical

class PythonExport():
    def __init__(self, model, latexSubs={}):
        self._Name = model._Name.replace('-', '').replace('+', '')
        if self._Name[0].isdigit():
            self._Name = '_' + self._Name
        self.model = model

        self.string = ""
        self.stringRun = ""

        # BetaFunc definition
        self.betaFactor = model.betaFactor
        self.betaExponent = str(model.betaExponent(Symbol('n')))

        self.translation = {'GaugeCouplings': 'Gauge Couplings',
                            'Yukawas': 'Yukawa Couplings',
                            'QuarticTerms': 'Quartic Couplings',
                            'TrilinearTerms' : 'Trilinear Couplings',
                            'ScalarMasses': 'Scalar Mass Couplings',
                            'FermionMasses': 'Fermion Mass Couplings',
                            'Vevs': 'Vacuum-expectation Values'}

        self.cListNames = {k:v.replace(' ', '') for k,v in self.translation.items()}
        self.cListNames['Vevs'] = 'Vevs'

        self.allCouplings = {}
        self.couplingStructure = {}

        self.couplingStructure = {pycode(model.allCouplings[k][1]): v for k,v in model.couplingStructure.items()}

        self.yukLikeCouplings = {}

        self.conjugatedCouplings = {}
        self.cDic = {}

        self.inconsistentRGset = (model.NonZeroCouplingRGEs != {} or model.NonZeroDiagRGEs != {})

        if self.inconsistentRGset:
            raise TypeError("     -> Error : The RGE set is inconsistent. Please refer to the latex output.")

        self.gaugeFixing = False
        self.RGfileString = {}
        self.allBetaFunctions = {}

        # Initialize the latex substitutions
        self.latex = {pycode(k):v for k,v in latexSubs.items()}

        # Fix the symbolic gen numbers
        self.symbolicGens = []
        self.genFix = ''
        for p in model.Particles.values():
            if isinstance(p.gen, Symbol):
                if p.gen not in self.symbolicGens:
                    self.symbolicGens.append(p.gen)

        if self.symbolicGens != []:
            self.genFix = ' = '.join([str(el) for el in self.symbolicGens]) + ' = 3'

        self.preamble(model)
        self.RGsolver(model)

    def write(self, path):
        tmpDir = os.getcwd()

        if not os.path.exists(os.path.join(path, 'PythonOuput')):
            os.makedirs(os.path.join(path, 'PythonOuput'))

        # First : write the Python solver module
        fileName = os.path.join(path, 'PythonOuput', self._Name + '.py')
        try:
            self.file = open(fileName, 'w')
        except:
            loggingCritical('ERROR while creating the Python output file. Skipping.')
            return

        self.file.write(self.string)
        self.file.close()

        # Then, create the file containing the expression of the beta-functions
        fileName = os.path.join(path, 'PythonOuput', 'RGEs.py')
        try:
            self.file = open(fileName, 'w')
            self.file.write(self.RGEfileString())
        except:
            loggingCritical('ERROR while creating the Python RGE file. Skipping.')
            return
        self.file.close()

        # Finally create and write the run.py file
        os.chdir(os.path.join(path, 'PythonOuput'))
        self.runString(self.model, os.path.join(path, 'PythonOuput'))
        os.chdir(tmpDir)

        fileName = os.path.join(path, 'PythonOuput', 'run.py')
        try:
            self.file = open(fileName, 'w')
            self.file.write(self.stringRun)
        except:
            loggingCritical('ERROR while creating the Python run file. Skipping.')
            return

        self.file.close()

    def preamble(self, model):
        name = 'Model  : ' + model._Name
        auth = 'Author : ' + model._Author
        date = 'Date   : ' + model._Date
        self.string += f"""\
#########################################################
##  This file was automatically generated by PyR@TE 3  ##
###                                                   ###
##                                                     ##
#  {name+(53-len(name))*' '+'#'}
#  {auth+(53-len(auth))*' '+'#'}
#  {date+(53-len(date))*' '+'#'}
#########################################################
"""
        self.string += """
import time
import numpy as np
from sympy import flatten
from scipy.integrate import ode
import matplotlib.pyplot as plt

class Coupling():
    couplings = {}

    def __init__(self, name, couplingType, latex=None, shape = (), fromMat=None, cplx=False, init=0, pos=None):
        self.name = name
        self.type = couplingType

        if latex is not None:
            self.latex = latex
        else:
            self.latex = self.name

        self.shape = shape
        self.is_matrix = ( shape != () )
        self.nb = self.shape[0]*self.shape[1] if self.is_matrix else 1
        self.cplx = cplx

        self.initialValue = init if shape == () else np.zeros(shape)

        if fromMat is not None:
            self.pos = pos
            self.latex = '{' + fromMat.latex + '}' + self.name.replace(fromMat.name, '')
            return

        if couplingType not in self.couplings:
            self.couplings[couplingType] = []

        self.pos = sum([c.nb for cList in self.couplings.values() for c in cList])
        self.couplings[couplingType].append(self)

    def as_explicit(self, toList=False):
        if not self.is_matrix:
            return self

        nameFunc = lambda x: self.name+'_{' + str(1 + x // self.shape[1]) + str(1 + x % self.shape[1]) + '}'
        initFunc = lambda x: list(self.initialValue)[x // self.shape[1]][x % self.shape[1]]
        arrayFunc = np.vectorize(lambda x: Coupling(nameFunc(x), self.type, fromMat=self, init=initFunc(x), pos=self.pos+x))
        array = arrayFunc(np.reshape(range(self.nb), self.shape))

        if not toList:
            return array

        return [*array.flat]

"""

    def RGsolver(self, model):
        s = '''
class RGEsolver():
    """ This class contains the RGEs of the model, as well as pre-defined functions
    used to solve and plot them.

    The three following arguments may be provided:
        - initialScale:
            The energy scale at which the initial values are given
        - tmin, tmax :
            The lower and upper energy scales between which the running couplings are computed and plotted

    The initialScale can be different from tmin and tmax, the only requirement being that the initial value of the
    couplings are all given at the same scale."""

    translation = {'GaugeCouplings': 'Gauge Couplings',
                   'Yukawas': 'Yukawa Couplings',
                   'QuarticTerms': 'Quartic Couplings',
                   'TrilinearTerms' : 'Trilinear Couplings',
                   'ScalarMasses': 'Scalar Mass Couplings',
                   'FermionMasses': 'Fermion Mass Couplings',
                   'Vevs': 'Vacuum-expectation Values'}

    def __init__(self, name, initialScale = 0, tmin = 0, tmax = 20):
        if initialScale < tmin or initialScale > tmax:
            exit(f"The initial running scale must lie in the interval [tmin={tmin}, tmax={tmax}]")

        self.name = name
        Coupling.couplings = {}

        self.initialScale = initialScale
        self.tmin = tmin
        self.tmax = tmax

        self.kappa = lambda n: 1/(4*np.pi)**(''' + self.betaExponent + ''')
        self.kappaString = '1/(4*np.pi)**(''' + self.betaExponent + ''')'

        self.tList = []
        self.solutions = {}
        '''

        s += "self.loops = " + pycode({k:v for k,v in model.loopDic.items() if k in model.toCalculate}, end='\n'+22*' ')

        if self.genFix != '':
            s += """

        # Fix the symbolic generation numbers
        """ + self.genFix

        s += self.couplingsDefinition(model)

        s += """

        self.couplings = Coupling.couplings
        self.matrixCouplings = {c.name: np.vectorize(lambda x: x.name)(c.as_explicit())
                                for cList in self.couplings.values()
                                for c in cList if c.is_matrix}


    def extractCouplings(self, couplingsArray, couplingType):
        ret = []
        for c in self.couplings[couplingType]:
            if not c.is_matrix:
                ret.append(couplingsArray[c.pos])
            else:
                ret.append(np.matrix(np.reshape([couplingsArray[p] for p in range(c.pos, c.pos+c.nb)], c.shape)))
        return ret
"""

        if self.gaugeFixing:
            s += """

    def fixGauge(self, xi):
        self.xiGauge = xi
"""
        s += self.RGEs(model)

        s += r'''


    def printInitialConditions(self, returnString=False):
        """ This function displays the current running scheme and the initial values of the couplings.

        Its output may be copy-pasted 'as-is' by user to modify these parameters before solving the RGEs."""

        # Display the running scheme

        outputString = "\n# Running scheme :\n\n"

        s = f"{self.name}.loops = "
        outputString += s + str(self.loops).replace(', ', ',\n ' + ' '*len(s)) + '\n'

        # Display the initial values of the couplings
        for cType, cList in self.couplings.items():
            outputString += f"\n# {self.translation[cType]}\n\n"
            for c in cList:
                s = f"{self.name}.{c.name}.initialValue = "
                if not c.is_matrix:
                    s += str(c.initialValue)
                else:
                    sVal = '['
                    sVal += (',\n ' +  len(s)*' ').join([ str(el).replace(' ', ', ') for el in c.initialValue])
                    sVal += ']\n'
                    s += sVal
                outputString += s + '\n'

        if returnString:
            return outputString

        print(outputString)
'''

        s += r'''

    ##################
    # Solve function #
    ##################

    def solve(self, step=.1, Npoints=None):
        """ This function performs the actual solving of the system of RGEs, using scipy.ode.

        Either the step of the numerical integration may be provided by the user with 'step=[value]',
        OR the number of integration points with 'Npoints=[integer value]'."""

        self.allCouplings = flatten([c.as_explicit(toList=True) for cList in self.couplings.values() for c in cList])

        time0 = time.time()
        y0 = flatten([(c.initialValue if not c.is_matrix else [*c.initialValue.flat]) for c in self.allCouplings])

        tmin = self.tmin
        tmax = self.tmax
        t0 = self.initialScale

        if Npoints is None:
            dt = step
        else:
            dt = (tmax-tmin)/(Npoints-1)

        solutions = {}
        for c in self.allCouplings:
            solutions[c.name] = []
        tList = []

        solver = ode(self.betaFunction).set_integrator('zvode', method='bdf')
        solver.set_initial_value(y0, t0)

        # Solve upwards
        while solver.successful() and solver.t < tmax + dt/2:
            tList.append(solver.t)
            for i, c in enumerate(self.allCouplings):
                y = solver.y[i]
                if abs(y.imag) > 1e-10 and not c.cplx:
                    c.cplx = True
                elif y.imag == 0:
                    y = y.real

                solutions[c.name].append(y)

            solver.integrate(solver.t+dt)

        if t0 > tmin:
        # If t0 > tmin, complete the solving going downwards
            solutions2 = {}
            for c in self.allCouplings:
                solutions2[c.name] = []
            tList2 = []

            solver.set_initial_value(y0, t0)
            # Solve downwards
            while solver.successful() and solver.t > tmin - dt/2:
                solver.integrate(solver.t-dt)

                tList2.append(solver.t)
                for i, c in enumerate(self.allCouplings):
                    y = solver.y[i]
                    if abs(y.imag) > 1e-10 and not c.cplx:
                        c.cplx = True
                    elif y.imag == 0:
                        y = y.real

                    solutions2[c.name].append(y)


            # Combine the two regions
            tList = tList2[::-1] + tList
            for c in self.allCouplings:
                solutions[c.name] = solutions2[c.name][::-1] + solutions[c.name]

        self.tList, self.solutions = np.array(tList), {k:np.array(v) for k,v in solutions.items()}

        for k,v in self.matrixCouplings.items():
            self.solutions[k] = np.zeros(v.shape).tolist()
            for i, l in enumerate(self.solutions[k]):
                for j in range(len(l)):
                    self.solutions[k][i][j] = self.solutions[v[i,j]].tolist()
            self.solutions[k] = np.array(self.solutions[k]).transpose([2,0,1])

        print(f"System of RGEs solved in {time.time()-time0:.3f} seconds.")


    #################
    # Plot function #
    #################

    subPos = {1: [111], 2: [121, 122], 3:[221, 222, 212],
              4: [221, 222, 223, 224], 5:[231, 232, 233, 223, 224],
              6: [231, 232, 233, 234, 235, 236],
              7: [241, 242, 243, 244, 231, 232, 233]}

    def plot(self, figSize=(600, 600), subPlots=True, which={}, whichNot={}, printLoopLevel=True):
        """ Plot the running couplings.

        Several options may be given to this function:
            - figSize=(x,y):
                The figure dimensions in pixels.
            - subPlots=True/False :
                If True, plot all the various couplings in the same window. If False,
                produces one figure by coupling type.
            - which=... :
                The user may want to plot only one or several (types of) couplings. Usage:

                >>> which='GaugeCouplings'

                >>> which=('GaugeCouplings', 'QuarticTerms')

                >>> which={'GaugeCouplings': 'all', 'Yukawas': ['yt', 'yb']}

                >>> which={'GaugeCouplings': ['g1', 'g2], 'Yukawas': 'Yu_{33}'}
            - whichNot=... :
                Which types of coupling types are NOT to be plotted. Same usage as which.
                Note that 'which' and 'whichNot' cannot be used simultaneously.
            - printLoopLevel=True/False :
                The loop-levels of the computation are displayed in the title of the plots.
        """

        if self.solutions == {}:
            print("The system of RGEs must be solved before plotting the results.")
            return

        allCouplingsByType = {cType:[] for cType in self.couplings}

        for c in self.allCouplings:
            if not all([el == 0 for el in self.solutions[c.name]]):
                allCouplingsByType[c.type].append(c)

        if which != {} and whichNot != {}:
            print("Error in 'plot' function: Arguments 'which' and 'whichNot' cannot be used simultaneously.")
            return

        ########################################
        # Identify the couplings to be plotted #
        ########################################

        if type(which) == str:
            which = {which: 'all'}
        elif type(which) == tuple:
            which = {el: 'all' for el in which}
        if type(whichNot) == str:
            which = {which: 'all'}
        elif type(whichNot) == tuple:
            whichNot = {el: 'all' for el in whichNot}

        for cType, cList in list(allCouplingsByType.items()):
            couplingsToDelete = []
            toDelete = False
            if cList == []:
                toDelete = True
            if which != {}:
                if cType not in which:
                    toDelete = True
                elif which[cType] != 'all':
                    if type(which[cType]) == str:
                        which[cType] = [which[cType]]
                    tmpList = []
                    for el in which[cType]:
                        if el not in self.matrixCouplings:
                            tmpList.append(el)
                        else:
                            tmpList += [*self.matrixCouplings[el].flat]
                    couplingsToDelete = [c for c in cList if c.name not in tmpList]
            if whichNot != {}:
                if cType in whichNot:
                    if whichNot[cType] == 'all':
                        toDelete = True
                    else:
                        if type(whichNot[cType]) == str:
                            whichNot[cType] = [whichNot[cType]]
                        tmpList = []
                        for el in whichNot[cType]:
                            if el not in self.matrixCouplings:
                                tmpList.append(el)
                            else:
                                tmpList += [*self.matrixCouplings[el].flat]
                        couplingsToDelete = [c for c in cList if c.name in tmpList]

            if toDelete:
                del allCouplingsByType[cType]

            if couplingsToDelete != []:
                for c in couplingsToDelete:
                    if c in allCouplingsByType[cType]:
                        allCouplingsByType[cType].remove(c)


        ###################
        # Actual plotting #
        ###################

        if subPlots:
            plt.figure(figsize=(figSize[0]/80., figSize[0]/80.), dpi=80)

        for i, (cType, cList) in enumerate(allCouplingsByType.items()):
            title = self.translation[cType]
            if printLoopLevel:
                title = f"{self.loops[cType]}-loop " + title
            if not subPlots:
                plt.figure(figsize=(figSize[0]/80., figSize[0]/80.), dpi=80)
                plt.suptitle(title)
            else:
                plt.subplot(self.subPos[len(allCouplingsByType)][i])
                plt.title(title)

            cNames = []
            for c in cList:
                if not c.cplx:
                    plt.plot(self.tList, self.solutions[c.name])
                    cNames.append('$' + c.latex + '$')
                else:
                    plt.plot(self.tList, np.real(self.solutions[c.name]))
                    plt.plot(self.tList, np.imag(self.solutions[c.name]))
                    cNames.append('$\\Re(' + c.latex + ')$')
                    cNames.append('$\\Im(' + c.latex + ')$')

            plt.legend(cNames)
            plt.xlabel(r't',fontsize=17-len(allCouplingsByType))


    #########################
    # Save / load functions #
    #########################

    def save(self, fileName):
        try:
            import pickle
        except:
            print("Error: unable to load the 'pickle' module.")
            return

        storeKappa = self.kappa
        self.kappa = None

        try:
            if '.' not in fileName:
                fileName += '.save'
            print(f"Saving the RGE object in file '{fileName}'...", end='')
            file = open(fileName, 'wb')
            pickle.dump(self, file)
        except BaseException as e:
            print("\nAn error occurred while saving the rge object :")
            print(e)
        else:
            print(" Done.")
        finally:
            file.close()

        self.kappa = storeKappa

    def load(fileName):
        import os
        try:
            import pickle
        except:
            print("Error: unable to load the 'pickle' module.")
            return

        if not os.path.exists(fileName):
            print(f"Error: The file '{fileName}' doesn't exist.")
            return None

        try:
            print(f"Loading the RGE object from file '{fileName}'...", end='')
            file = open(fileName, 'rb')
            rge = pickle.load(file)
        except BaseException as e:
            print("\nAn error occurred while loading the rge object :")
            print(e)
        else:
            print(" Done.")
        finally:
            file.close()

        rge.kappa = eval('lambda n:' + rge.kappaString)
        return rge

'''

        self.string += s


    def couplingsDefinition(self, model):
        s = ""

        substitutedCouplings = [str(k) for subDic in model.substitutions.values() for k in subDic]

        for cType in model.toCalculate:
            if 'Anomalous' in cType:
                continue

            self.cDic[cType] = {}
            for k,v in model.allCouplings.items():
                if v[0] == cType and k not in substitutedCouplings:
                    # The conjugated couplings are removed, and must be replaced by Conjugate[ ... ]
                    if not k[-2:] == '^*' and not k[-4:] == '^{*}' and not k[-4:] == 'star':
                        self.cDic[cType][v[1]] = pycode(v[1]).replace('{', '').replace('}', '')
                        self.allCouplings[k] = pycode(v[1]).replace('{', '').replace('}', '')
                    else:
                        candidates = [el for el in model.allCouplings if el in k and el != k]
                        if len(candidates) == 1:
                            self.conjugatedCouplings[k] = candidates[0]
                        else:
                            lengths = [len(el) for el in candidates]
                            i, maxLen = lengths.index(max(lengths)), max(lengths)
                            lengths.remove(maxLen)

                            if maxLen not in lengths:
                                self.conjugatedCouplings[k] = candidates[i]
                            else:
                                loggingCritical(f"Warning in Python export: could not determine the conjugate quantity of {k} automatically." +
                                                "\n -> The user will have to modify the output Python file manually.")

            s += f"\n\n        # {self.translation[cType]}"

            if cType == 'Vevs' and model.gaugeFixing is None:
                s += "\n        #   For vevs the gauge must be fixed. Let's use for instance the Landau gauge :\n"
                s += "        self.xiGauge = 0\n"
                self.gaugeFixing = True

            for c, cName in self.cDic[cType].items():
                s += f"\n        self.{cName} = Coupling('{cName}', '{cType}'"
                if cName in self.latex:
                    s += ", latex='" + self.latex[cName].replace('\\', '\\\\').replace("'", "\\'") + "'"
                if isinstance(c, mSymbol):
                    s += ', shape=' + str(c.shape).replace(' ', '')
                s += ')'

        return s


    def RGEs(self, model):
        s = '''\n
    def betaFunction(self, t, couplingsArray):
        """ This function generates the numerical values of the model RGEs. It is called by the
            solver to provide the derivative of the couplings with respect to the energy scale."""\n\n'''

        betaInitString = ""
        for cType, dic in self.cDic.items():
            s += "        " + ', '.join(dic.values()) + (',' if len(dic) == 1 else '') + ' = '
            s += f"self.extractCouplings(couplingsArray, '{cType}')\n"

            betaInitString += "        b" + ', b'.join(dic.values())
            if len(dic) == 1:
                betaInitString += ' = 0\n'
            else:
                betaInitString += f' = {len(dic)}*[0]\n'

        s += '\n' + betaInitString

        for cType, loopDic in model.couplingRGEs.items():
            if 'Anomalous' in cType:
                continue

            argsDic = {}
            for nLoop, RGEdic in loopDic.items():
                for c, RGE in RGEdic.items():
                    if c not in self.allCouplings:
                        continue
                    args = [v for k,v in self.allCouplings.items() if RGE.find(model.allCouplings[k][1]) != set()]

                    if RGE.find(Symbol('_xiGauge', real=True)) != set():
                        args.append('xiGauge')

                    if cType not in argsDic:
                        argsDic[cType] = {}
                    if c not in argsDic[cType]:
                        argsDic[cType][c] = args
                    else:
                        argsDic[cType][c] += [el for el in args if el not in argsDic[cType][c]]

            s += '\n'
            for nLoop, RGEdic in loopDic.items():
                s += f"        if self.loops['{cType}'] >= {nLoop+1}:\n"
                for c, RGE in RGEdic.items():
                    if c not in self.allCouplings:
                        continue

                    betaName = 'beta_' + self.allCouplings[c]
                    args = ['nLoop'] + argsDic[cType][c]
                    betaString = (betaName + '(' + ','.join(args) + ')').replace('nLoop,', 'nLoop, ')

                    if cType not in self.RGfileString:
                        self.RGfileString[cType] = {}
                    if c not in self.RGfileString[cType]:
                        self.RGfileString[cType][c] = {}
                    if 'def' not in self.RGfileString[cType][c]:
                        self.RGfileString[cType][c]['def'] = betaString
                    if cType not in self.allBetaFunctions:
                        self.allBetaFunctions[cType] = []
                    if betaName not in self.allBetaFunctions[cType]:
                        self.allBetaFunctions[cType].append(betaName)

                    betaString = betaString.replace('nLoop', str(nLoop+1)).replace('xiGauge', 'self.xiGauge')

                    self.RGfileString[cType][c][nLoop] = pycode(RGE/self.betaFactor)

                    s += 12*' ' + f'b{pycode(Symbol(c))} += ' + betaString + '*self.kappa(' + str(nLoop+1) + ')'
                    s += '*np.log(10)\n'

        s += '\n        return ['
        s += ', '.join([('b'+v if k not in self.couplingStructure else f'*b{v}.flat') for k,v in self.allCouplings.items()])
        s += ']'


        importBetaFuncs = '\n\nfrom RGEs import ('
        importBetaFuncs += (',\n' + 18*' ').join([', '.join(betaFuncs) for cType, betaFuncs in self.allBetaFunctions.items()])
        importBetaFuncs += ')'

        pos = self.string.find('import matplotlib.pyplot as plt') + len('import matplotlib.pyplot as plt')
        self.string = self.string[:pos] + importBetaFuncs + self.string[pos:]

        return s

    def RGEfileString(self):
        s = f"""#####################################################################
#       This file was automatically generated by PyR@TE 3.
# It contains the expressions of the RGEs of the model '{self.model._Name}'.
#####################################################################

import numpy as np

tr = lambda x: np.trace(x)
adjoint = lambda x: x.H
transpose = lambda x: x.transpose()
conjugate = lambda x: np.conjugate(x)"""

        if self.genFix != '':
            s += """

# Fix the symbolic generation numbers
""" + self.genFix

        for cType, RGEs in self.RGfileString.items():
            sType = self.translation[cType]
            s += '\n\n\n' + '#'*(len(sType)+4) + '\n'
            s += '# ' + sType + ' #\n'
            s += '#'*(len(sType)+4)

            for c, loopDic in RGEs.items():
                s += '\n\n' + 'def ' + loopDic['def'] + ':'
                del loopDic['def']
                for nLoop, RGE in loopDic.items():
                    s += f'\n    if nLoop == {nLoop+1}:\n'
                    s += '        return ' + RGE
        return s

    def runString(self, model, path):
        self.stringRun = "import sys\n"
        path = path.replace('\\', '\\\\')
        self.stringRun += f"sys.path.append('{path}')\n\n"
        self.stringRun += "from " + self._Name + " import RGEsolver"

        self.stringRun += """\n
##############################################
# First, create an instance of the RGEsolver #
##############################################

rge = RGEsolver('rge', tmin=0, tmax=20, initialScale=0)\n"""

        # Actually import the generated Python file and create the rge object
        exec(self.stringRun, globals(), globals())

        global initialString
        initialString = ""
        exec("initialString = rge.printInitialConditions(returnString=True)", globals(), globals())

        self.stringRun += """\n
##########################################################
# We fix the running scheme and initial conditions below #
##########################################################
"""

        self.stringRun += initialString
        self.stringRun += """\n
############################
# Solve the system of RGEs #
############################

rge.solve(step = .05)

# Another way to call rge.solve() :
# rge.solve(Npoints = 500)

####################
# Plot the results #
####################

rge.plot(subPlots=True, printLoopLevel=True)


#############################################
# Possibly save the results for a later use #
#############################################

# Save the results in some file

# rge.save('rgeResults.save')

# Later, load the rge object with :

# rge = RGEsolver.load('rgeResults.save')

"""

class Printer(PythonCodePrinter):

    def __init__(self, end=''):
        PythonCodePrinter.__init__(self)
        self.end  = end

    def _print_dict(self, expr):
        s = '{'
        for i,(k,v) in enumerate(expr.items()):
            s += f"'{k}' : {v}"
            if i < len(expr)-1:
                s += ', ' + self.end
        s += '}'

        return s

    def _print_Symbol(self, expr):
        if expr == Symbol('_xiGauge', real=True):
            # return 'self.xi'
            return 'xiGauge'

        ret = super(PythonCodePrinter, self)._print_Symbol(expr)
        ret = ret.replace('\\', '')

        return ret

    def _print_Pi(self, expr):
        return 'np.pi'

    def _print_adjoint(self, expr):
        return 'adjoint(' + pycode(expr.args[0]) + ')'

    def _print_transpose(self, expr):
        return 'transpose(' + pycode(expr.args[0]) + ')'

    def _print_conjugate(self, expr):
        return 'conjugate(' + pycode(expr.args[0]) + ')'

    def _print_Trace(self, expr):
        return 'tr(' + pycode(expr.args[0]) + ')'

    def _print_Mul(self, expr):
        if expr.find(conjugate) != set():
        # Substitution x * conjugate(x) -> abs(x)^2
            conjArgs = {}
            args = splitPow(expr)
            for el in args:
                if isinstance(el, conjugate) or el.is_commutative == False or el.is_real:
                    continue
                else:
                    count = min(args.count(el), args.count(conjugate(el)))
                    if count != 0:
                        conjArgs[el] = count
            if conjArgs != {}:
                for k,v in conjArgs.items():
                    for _ in range(v):
                        args.remove(k)
                        args.remove(conjugate(k))
                        args.append(Abs(k)**2)
                expr = Mul(*args)

        return super()._print_Mul(expr)


def pycode(expr, **settings):
    return Printer(**settings).doprint(expr)

