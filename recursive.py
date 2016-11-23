from __future__ import division, absolute_import, print_function
import weakref
import inspect
import copy
from glob import fnmatch, has_magic


class SubstitutionError(RuntimeError):
    pass

class ArgSpec(object):
    """ Object for recfunc that contain the arguments substitution rules and method """
    def __init__(self, nposargs, args, anyposargs=False, anykwargs=False, mendatories=None):
        self.nposargs = nposargs
        self.args = args
        self.anykwargs = anykwargs
        self.anyposargs = anyposargs
        self.mendatories = set()

    def substitute_args(self, obj, args, kwargs, offset=0):
        """ substitute the args list and kwargs dict from a called object 

        Everythin not found in args or kwargs is replaced by obj[key]
        Raise an error if some positional argument is missing.
        """
        fargs = list(self.args[offset:])        
        args = list(args)
        if self.anyposargs:
            pass
        else:    
            for a,v in zip(self.args[offset:self.nposargs], args):
                fargs.remove(a)
            for i,a in enumerate(self.args[len(args)+offset:self.nposargs],start=len(args)+offset):
                try:
                    v = obj[a]
                except KeyError:                    
                    raise SubstitutionError("Can't substitute the #%d positional argument with key %r"%(i,a))
                    
                fargs.remove(a)                         
                args.append(v)   

        if self.anykwargs:
            allkwargs = dict(**obj)            
            kwargs = dict(allkwargs, **kwargs)

        else:                      
            for a,v in kwargs.iteritems():
                try:
                    fargs.remove(a)
                except ValueError:
                    pass

            for a in fargs:
                try:
                    v = obj[a]
                except KeyError:                    
                    pass                
                else:
                    kwargs[a] = v
        return tuple(args), kwargs

    @classmethod
    def from_recargs(cl, *args, **kwargs):
        """ Build the ArgSpec for RecFunc object from a list of strings 
        
        signature is:
        ArgSpec.from_recargs( N, "a1", "a2", "a3", "a4")
        where N is the number of mendatory positional arguments followed their names. 
        If the number of names are greater than N they are understood as optional keyword
        arguments.                
        """
        mendatories = kwargs.pop("mendatories", set())
        if not args:
            return cl(0, [], False, False)


        a0 = args[0]
        if a0 is True:
            nposargs = 0
            anyposargs = True
            n = 1
            # remove the True
            args = args[1:]                
        elif isinstance(a0, int):
            nposargs = a0
            n = a0
            anyposargs = False        
            #remove the integer    
            args = args[1:]
        else:
            nposargs = 0
            n = 0
            anyposargs = False    


        if len(args)>n and args[n] is True:
            anykwargs = True
            if len(args[n+1:]):
                raise TypeError("No more args accepted after 'True'")
            args = args[1:]    
        else:
            anykwargs = False
        return cl(nposargs, args, anyposargs, anykwargs, mendatories=mendatories)
    
    @classmethod
    def from_method(cl, f, mendatories=None):
        """ Build the ArgSpec from a method definition. 
        
        An optional mendatories argument gives a list of mendatory keyword before calling the function.
        """
        spec = inspect.getargspec(f)

        defaults = spec.defaults or []
        n = len(spec.args)-len(defaults)
        args = spec.args

        if spec.varargs:  
            nposargs = 0
            anyposargs = True

        else:    
            nposargs = n
            anyposargs = False
        if spec.keywords:
            anykwargs = True
        else:
            anykwargs = False
        return cl(nposargs, args, anyposargs, anykwargs, mendatories=mendatories)
     



class BaseRecObject(object):

    parameters = {}
    sharedparameters = {}
    prototypes = {}
    """ Class parameters """
    blocked = set()
    """ A set of blocked keywords, they will not be taken from parents """
    __imro__ = tuple()
    __imro_slices__ = (slice(0,0), slice(0,0), slice(0,0))
    __iid__  = None
    recursive = True

    def __init__(self, __d__={}, **kwargs):
        __imro__ = []
        shared = {}
        #####
        # collect the class definition 
        # will be done in a metaclass in the future 
        for sub in self.__class__.__mro__:
            if isinstance(sub, type):            
                try:
                    p = sub.__dict__["parameters"]
                    #p = getattr(sub, "parameters")
                except KeyError:#AttributeError:
                    pass
                else:                
                    __imro__.append(p)

                try:
                    p = sub.__dict__["sharedparameters"]
                    #p = getattr(sub, "parameters")
                except KeyError:#AttributeError:
                    pass
                else:                
                    for k,v in p.iteritems():
                        shared.setdefault(k,v)    

        ##
        # __imro__ is composed of instance dictionaries, class parameters dictionary and
        # parent dictionaries    
        self.__imro__ = (shared,)+tuple(__imro__)

        # record the number of imro when the object has been initialized 
        # first  slice __imro__ of instance 
        # second slice __imro__ of classes definition
        # last   slice __imro__ of parent object 
        n = len(self.__imro__)
        self.__nimro_at_init__ = n# ((0,0), (0,1), (1,len(__imro__)), (0,0))
        self.__imro_slices__ = (slice(0,1), slice(1,n), slice(n,None))
        ##
        # the __iid__ is used in __get__ to identify the object inside the 
        # parent instance 
        self.__iid__ = id(self)
        ##
        # update the __imro__[0] (this instance)        
        self.blocked = set(self.blocked)
        self.prototypes = dict(self.prototypes)
        #self.locals.update(__d__, **kwargs)
        for k,v in kwargs.iteritems():
            self[k] = v

    def __gettrueitem__(self, item):
        if item in self.blocked:
            ## blocked item concerned only the instance and class dictionaries 
            imro = self.__imro__[self.__imro_slices__[0]]+self.__imro__[self.__imro_slices__[1]]
        else:
            imro = self.__imro__

        for obj in imro:
            try:
                return obj, obj[item]                
            except KeyError:
                pass                               
        raise KeyError("%r"%item)    

    def __getitem__(self, item):
        """ 
        obj[key] -> return the value transformed eventualy by __rec_get__
        obj[key,]  -> return the true object 
        """
        
        truevalue = False    
        if isinstance(item, tuple):
            if len(item)>1:
                raise TypeError("Indice must not be a tuple with len>1")
            item, = item
            truevalue = True    


        D, value = self.__gettrueitem__(item)

        if truevalue:
            return value
        if hasattr(value, "__rec_get__"):
            return value.__rec_get__(self,D,item)    
        return value

    def __setitem__(self, item , value):
        """
        obj[key] = value -> set the value transformed eventualy by __rec_set__
        obj[key,] = value  -> set the true value object 
        """
        
        if isinstance(item, tuple):
            item, = item
            self.locals[item] = value
        else:
            try:   
                D, realvalue = self.__gettrueitem__(item)
            except KeyError:
                if item in self.prototypes:
                    v = self.prototypes[item](value)
                    self.locals[item] = v
                else:    
                    self.locals[item] = value
            else:    
                if hasattr(realvalue, "__rec_set__"):
                    realvalue.__rec_set__(self, D, item, value)
                else:
                    if item in self.prototypes:
                        v = self.prototypes[item](value)
                        self.locals[item] = v
                    else:    
                        self.locals[item] = value

    def __delitem__(self, item):        
        del self.locals[item]   

    def block(self, *a):
        """ block a list of argument from being taken from parents """
        self.blocked.update(a)    
    
    def release(self, *keys):
        """ release a list of arguments if they have been blocked """
        for k in keys:
            try:
                self.blocked.remove(k)
            except KeyError:
                pass        
        
    def clone(self, **kwargs):
        """ clone the curent RecObject 

        The clone will not have the parents keyword values 
        Will have the child RecObject cloned

        """
        new = self._clone(tuple())
        new.__parent__ = None
        new.locals.update(kwargs)
        return new

    def _clone(self, pirmo):                        
        ## if it is instanced we need to clone without the parent dependancy 
        ## that mean everything after self.__nimro_at_init__+1
        sls = self.__imro_slices__
         ## everything comming from instance is removed 
        #__imro__ = self.__imro__[sls[0].start:sls[1].stop]
        
        imro_i  = ({},)+self.__imro__[sls[0]]
        imro_cl =       self.__imro__[sls[1]]
        imro_p =        self.__imro__[sls[2]]

        new = copy.copy(self)
        new.__recobj__ = {}
        new.__orecobj__ = {}
        new.__recfunc__ = {}
        new.__orecfunc__ = {}

        new.__imro__ = imro_i+imro_cl+pirmo        
        n = len(new.__imro__)
        new.__imro_slices__ = (slice(0,1), slice(1,n), slice(n,None)) 
         

        d  = getattr(self, "__recobj__",  {})
        od = getattr(self, "__orecobj__", {})

        df  = getattr(self, "__recfunc__",  {})
        odf = getattr(self, "__orecfunc__", {})


        for ids,obj in d.iteritems():                                 
            new.__orecobj__[ids] = obj._clone(imro_i+imro_p+pirmo)               
            
        for ids,obj in od.iteritems():
            if not ids in new.__orecobj__:                          
                new.__orecobj__[ids] = obj._clone(imro_i+imro_p+pirmo)                

        ###
        # clone the rec func imro instances 
        for ids,fmro in df.iteritems():                                             
            new.__orecfunc__[ids] = ({},)+fmro               
            
        for ids,fmro in odf.iteritems():
            if not ids in new.__orecfunc__:                          
                new.__orecfunc__[ids] = ({},)+fmro

        return new 



    @property
    def locals(self):
        """ Dictionary of local keyword, e.i. of this object instance """
        return self.__imro__[0]   

    @property
    def alls(self):
        """ build and return a dictionary containing all keywords/value pairs found in the hierarchy """
        d = {}
        for obj in self.__imro__[::-1]:
            d.update(**obj)
        return d

    def update(self, __d__={}, **kwargs):
        """D.update([E, ]**F) -> None.  Update D from dict/iterable E and F.
        If E present and has a .keys() method, does:     for k in E: D[k] = E[k]
        If E present and lacks .keys() method, does:     for (k, v) in E: D[k] = v
        In either case, this is followed by: for k in F: D[k] = F[k]
        """
        # instead of using .locals.update redefine the function in order to take into account
        # an eventual item with a __rec_set__ method 
        if hasattr(__d__, "keys"):
            for k in __d__.keys():
                self[k] = __d__[k]
        else:
            for k,v  in __d__:
                self[k] = v
        for k,v in kwargs.iteritems():
            self[k] = v 
        ## prefered to                            
        ## self.locals.update(__d__, **kwargs)        

    def setdefault(self, key, value):
        """D.setdefault(k[,d]) -> D.get(k,d), also set D[k]=d if k not in D"""
        try:
            return self[key]
        except KeyError:
            self[key] = value
            return value

    def keys(self):
        return self.alls.keys()

    def values(self):
        return self.alls.values()        

    def items(self):
        return self.alls.items()
    
    def iteritems(self):     
        """D.iteritems() -> an iterator over the (key, value) *ALL* items of D"""   
        for obj in self.__imro__:
            for k,v in obj.iteritems():
                yield k,v
    def iterkeys(self):
        """ D.iterkeys() -> an iterator over *ALL* the keys of D"""        
        for obj in self.__imro__:
            for k in obj.iterkeys():
                yield k

    def itervalues(self):   
        """ D.itervalues() -> an iterator over *ALL* the values of D"""     
        for obj in self.__imro__:
            for v in obj.itervalues():
                yield v

    __parent__ = None
    def get_parent(self):
        return self.__parent__ and self.__parent__()

    def __rcopy__(self, obj):
        return copy.copy(self)        

    def __get__(self, obj, cl):
        sid = id(self)

        if obj is None:
            return self
            #return RecFuncInstance(self, self.__imro__)
        
        if not self.recursive:
            return self
        
        if hasattr(obj, "__imro__"):
            obj_instanced = len(obj.__imro__[obj.__imro_slices__[0]])>1              
        else:
            obj_instanced = False    
        
        ## if obj is instanced record of new object is done in
        ## __recobj__, else record it in __orecobj__
        ## This is mendatory in case of sub-recobject hierarchy
        ##~~~~~~~~~~~~~~~~~~~`
        ## Class A(ro):
        ##    class B(ro):
        ##        class C(ro):
        ##            class D(ro):
        ##                pass
        ##            d = D()
        ##        c = C()
        ##        c.d['key'] = value
        ##    b1 = B()
        ##    b2 = B()
        ##  a = A()
        ##~~~~~~~~~~~~~~~~~~~~~ 
        ##  The  `c.d['key'] = value` needs to work in order to have 
        ##     a.b1.c.d and a.b2.c.d to work          

        #lookup = "__recobj__" if obj_instanced else "__orecobj__"

        #d  = obj.__dict__.setdefault(lookup, {})
        od = obj.__dict__.setdefault("__orecobj__", {})

        #idk = "__recobj_%s__"%sid
        idk = self.__iid__#+getattr(obj, "__ids__" , id(obj))
           
        ###############################
        #
        #
        #############################


        ###############################



        if obj_instanced:
            d  = obj.__dict__.setdefault("__recobj__", {})
            try:
                new = d[idk]
            except KeyError:
                try:
                    origin = od[idk]
                except KeyError:
                    new = self.__rcopy__( obj )
                    new.__parent__ = weakref.ref(obj)                     
                    origin = self
                    imro_i  = ({},)+self.__imro__[self.__imro_slices__[0]]
                    imro_cl =       self.__imro__[self.__imro_slices__[1]]
                    imro_p  =       self.__imro__[self.__imro_slices__[2]]    

                else:
                    new = copy.copy(origin)
                    new.__parent__ = weakref.ref(obj)  
                    imro_i  =       origin.__imro__[origin.__imro_slices__[0]]
                    imro_cl =       origin.__imro__[origin.__imro_slices__[1]]
                    imro_p  =       origin.__imro__[origin.__imro_slices__[2]]
                

                if hasattr(obj, "__imro__"):
                    ###
                    # add the imro of parent except the ones defined in the parent class  
                    imro_p += obj.__imro__[obj.__imro_slices__[0]]+obj.__imro__[obj.__imro_slices__[2]]    

                elif hasattr(obj,"__getitem__"):
                    imro_p += (obj,)



                new.__imro__ = imro_i+imro_cl+imro_p 
                n = len(imro_i)
                n2 = n + len(imro_cl)
                new.__imro_slices__ = (slice(0,n),slice(n,n2), slice(n2,None))
                                  
                d[idk] = new
        else:
            try:
                new = od[idk]
            except KeyError:
                new = self.__rcopy__( obj )
                new.__parent__ = weakref.ref(obj) 
                imro_i  = ({},)+self.__imro__[self.__imro_slices__[0]]
                imro_cl =       self.__imro__[self.__imro_slices__[1]]
                imro_p  =       self.__imro__[self.__imro_slices__[2]]

                

                if hasattr(obj, "__imro__"):
                    ###
                    # add the imro of parent except the ones defined in the class
                    imro_p += obj.__imro__[obj.__imro_slices__[0]]+obj.__imro__[obj.__imro_slices__[2]]    

                elif hasattr(obj,"__getitem__"):
                    imro_p += (obj,)
                

                new.__imro__ = imro_i+imro_cl+imro_p 
                n = len(imro_i)
                n2 = n + len(imro_cl)
                new.__imro_slices__ = (slice(0,n),slice(n,n2), slice(n2,None))

                od[idk] = new

        return new        

    



class RecObject(BaseRecObject):
    def __repr__(self):
        return "\n".join(_rec_repr(self.__imro__, [object.__repr__(self)], 0, set(self.blocked)))

    @classmethod    
    def add_class_child(cl, constructor, name, *args, **kwargs):
        if hasattr(cl, name):
            raise ValueError("Child %r already exists "%name)
        
        if isinstance(constructor, basestring):            
            try:
                constructor = getattr(cl, constructor)
            except AttributeError:
                raise AttributeError("%r class has no attribute %r"%(cl.__name__, constructor))        

        setattr(cl, name, constructor(*args, **kwargs))        

    def deploy(self):
        return _deploy({}, self, None)

    def propagate(self,  data, 
                 dreader=lambda x:x, vreader=lambda x:x): 
        data = _unflat(data, dreader, vreader)       
        for k,v in data.iteritems():
            if k[:1]==".":
                sub = getattr(self,k[1:])
                if hasattr(sub, "propagate"):
                    sub.propagate(v)
            else:
                self[k] = v    



class RecFuncInstance(object):
    def __init__(self,  recfunc, fmro, parent):
        self.recfunc = recfunc     
        self.parent = parent 
        self.fmro = fmro
        self.__doc__ = recfunc.__doc__

    def __call__(self, *args, **kwargs):
        args, kwargs = self.recfunc.argspec.substitute_args(self, args, kwargs, offset=1)
        return self.recfunc.fcall(self.parent, *args, **kwargs)
  
    def __getitem__(self, item):
        for d in self.fmro:
            try:
                return d[item]
            except KeyError:
                pass    
        return self.parent[item]
    
    def __setitem__(self, item, value):
        self.fmro[0][item] = value
    
    def __delitem__(self, item):
        del self.fmro[0][item]



class RecFunc(object):
    fcall = None
    __rec_class__ = None
    _InstanceClass = RecFuncInstance
    def __init__(self, *args, **params):        
        f = None
        if args and isinstance(args[0], int):
            self.argspec = ArgSpec.from_recargs(*args)         
        elif args:
            if len(args)>1:
                raise ValueError("expecting a int followed with string args or one positional argument only")
            f = args[0]
            self.argspec = ArgSpec.from_method(f, **params)                                            
        else:
            self.argspec = ArgSpec(0,[],False,False)
                                                                 
        self.set_caller(f)#lambda *a,**k:(a,k) if f is None else f
        self.__fmro__ = ({},)
        self.__iid__ = id(self)

    def __get__(self, obj, cl):
        sid = id(self)

        if obj is None:
            return self
            #return RecFuncInstance(self, self.__imro__)        
        if hasattr(obj, "__imro__"):
            obj_instanced = len(obj.__imro__[obj.__imro_slices__[0]])>1              
        else:
            obj_instanced = False    
        
        
        od = obj.__dict__.setdefault("__orecfunc__", {})

        idk = self.__iid__


        if obj_instanced:
            d  = obj.__dict__.setdefault("__recfunc__", {})
            try:
                fmro = d[idk]
            except KeyError:
                try:
                    origin = od[idk]
                except KeyError:

                    fmro = ({},)+self.__fmro__
                    
                else:
                    fmro = ({},)+origin.__fmro__


                #if hasattr(obj,"__getitem__"):
                #    fmro += (obj,)

                d[idk] = fmro
        else:
            try:
                fmro = od[idk]
            except KeyError:
                fmro = ({},)+self.__fmro__
                
                #if hasattr(obj,"__getitem__"):
                #    fmro += (obj,)
                
                od[idk] = fmro

        return self._InstanceClass(self, fmro, obj)


    @classmethod
    def factory(cl, *args, **kwargs):
        if args:
            argspec = ArgSpec.from_recargs(*args)
            self = cl(0)
            self.argspec = argspec
            
            self.__fmro__[0].update(**kwargs)
            return self.caller 
        def builder(f):
            argspec = ArgSpec.from_method(f)
            self = cl(0)
            self.argspec = argspec
            
            self.__fmro__[0].update(**kwargs)
            return self.caller(f)
        return builder 
    
    def set_caller(self, fcall):
        """ set in place the fcall function """
        self.fcall = fcall
        # for now just copy the doc, will see after what to
        # do
        if getattr(fcall, "__doc__", None):
            self.__doc__ = fcall.__doc__

    def caller(self, fcall):
        """ same as set_caller but return the object """
        self.set_caller(fcall)
        return self

    def __getitem__(self, item):
        truevalue = False
        if isinstance(item, tuple):
            truevalue = True
            item, = item

        if truevalue:
            for d in self.__fmro__:
                try:
                    return d[item]
                except KeyError:
                    pass    
        else:        
            for d in self.__fmro__:
                try:
                    v =  d[item]
                except KeyError:
                    pass
                else:
                    if hasattr(v, "__rec_get__"):
                        return v.__rec_get__(self, d, item)
                    return v

        raise KeyError("%r"%item)
    
    def __setitem__(self, item, value):
        truevalue = False
        if isinstance(item, tuple):
            truevalue = True
            item, = item

        if truevalue:
            self.__fmro__[0][item] = value

        else:                
            try:
                v = self[item,]
            except KeyError:
                self.__fmro__[0][item] = value
            else:
                if hasattr(v, "__rec_set__"):
                    v.__rec_set__(self, self.__fmro__[0], item, value)    
                else:
                    self.__fmro__[0][item] = value
    
    def __delitem__(self, item):
        del self.__fmro__[0][item]    

    def __call__(self, *args, **kwargs):       
        if self.__rec_class__:
            if not isinstance(args[0], self.__rec_class__):
                raise ValueError("Expecting an instance of %s got %s"%(self.__rec_class__, type(recobj)))
            newargs, kwargs = self.argspec.substitute_args(self, args[1:], kwargs, offset=1)
            return self.fcall(args[0], *newargs, **kwargs)
        else:
            args, kwargs = self.argspec.substitute_args(self, args, kwargs)
            return self.fcall(*args, **kwargs)
                   

class StaticRecFunc(RecFunc):
    def __get__(self, obj, cl=None):
        if obj is None:
            return obj
        return RecStaticFuncInstance(self, obj)     





class RecStaticFuncInstance(RecFuncInstance):
    def __call__(self, *args, **kwargs):
        args, kwargs = self.recfunc.argspec.substitute_args(self, args, kwargs, offset=0)
        return self.recfunc.fcall(*args, **kwargs)


class StaticRecFunc(RecFunc):
    _InstanceClass = RecStaticFuncInstance


MAX_STRING_LEN = 60
def _rec_repr(mro, txts, level, keys=set()):
    
    if not mro:
        return txts

    idt = "-"*level
    ##
    # requirement for mro object is that they are mappable
    # and have __getittem__
    for key in mro[0].keys():
        if key in keys:
            continue
        value = mro[0][key]
        keys.add(key)
        s = repr(value)
        if len(s)>60:
            s = s[:56]+"...."
        txts.append( "%s%r : %s"%(idt,key,s)  )    
    return _rec_repr(mro[1:], txts, level+1, keys)    
        
def _deploy(d, obj, parent):
    for sub in obj.__class__.__mro__:
        for k,v in sub.__dict__.iteritems():
            if isinstance(v, RecObject):
                d["."+k] = _deploy({},getattr(obj,k), sub)
    if parent:
        for mro in obj.__imro__[::-1]:
            if not mro in parent.__imro__:
                d.update(**mro)  
    else:            
        d.update(obj.locals)
    return d                






def _rec_copy(ro):
    new = copy.copy(ro)
    
    od = dict(new.__dict__.setdefault("__orecobj__", {}))
    d  = dict(new.__dict__.setdefault("__recobj__", {}))

    new.__imro__ = ({},)+ro.__imro__
    for ids, obj in od.iteritems():
        d[ids] = _rec_copy(obj)
    return new    


def _unflat(d, dreader, vreader):
    d = dreader(d)
    od = {}
    tounflat = set()
    for k,v in d.iteritems():
        ok = k
        if isinstance(k, basestring) and k[:1]== ".":

            k, p, rest = k[1:].partition(".")            
            
            if not rest:
                ak, b, k = k.partition("[")
                if not k:
                    od["."+ak ] = v#dreader(v)
                else:
                    k, b, garbage =  k.partition("]")
                    if not b or garbage.strip():
                        ValueError("path error %r"%ok)
                    k = _pytonify_key(k)                                        
                    od.setdefault("."+ak, {})[k] = vreader(v)
                tounflat.add("."+ak)                                    
            else:
                sub = od.setdefault("."+k, {})
                sub["."+rest] = v
                tounflat.add("."+k)                                
        else:
            od[k] = vreader(v)
    for k in tounflat:
        od[k] = _unflat(od[k], dreader, vreader)
    return od

def _pytonify_key(k):
    try:
        return int(k)
    except ValueError:
        try:
            return float(k)
        except ValueError:
            return k                    

def _aunflat(d):
    d = copy.deepcopy(d)
    for k,v in d.items():
        if k[:1]== ".":
            path = k.split(k[1:])

            sp = path[-1].split("[")
            if len(sp)==1:
                fk = None
            elif len(sp)==2:
                path[-1], fk = sp
                try:
                    fk,garbage = fk.split("]")
                except ValueError:
                    raise ValueError("path error %r"%k)

                if garbage.strip():       
                    raise ValueError("path error %r"%k)

            tg = d
            while path:
                tg = tg.setdefault("."+path[0], {})
                path.pop(0)
            if fk:
                tg[fk] = v
            else:
                tg.update(**v)   
        

    return  d           



class cycle(object):
    def __init__(self,l):
        self.l = list(l)
        self.N = len(self.l)
        self.i = -1
    def next(self):
        self.i += 1
        return self.l[self.i%self.N]
    
    def __rec_get__(self, obj, d, key):
        v = self.next()    
        if hasattr(v, "__rec_get__"):
            return v.__rec_get__(obj,d, key)
        return v
                          
            
class alias(object):
    def __init__(self,f, doc=None):
        if isinstance(f, basestring):
            key = f
            f = lambda d:d[key]
            doc =  "-> o[%r]"%key if doc is None else doc
        self.f = f 
        if doc:
            self.__doc__ = doc

    def __rec_get__(self, obj, d,  key):
        v = self.f(obj)
        if hasattr(v, "__rec_get__"):
            return v.__rec_get__(obj, d, key)
        return v

    def __repr__(self):
        if self.__doc__:
            return "Alias: %s"%self.__doc__
        return object.__repr__(self)


##########################################################
#
#
##########################################################

def build_getter(tpe,core,value):
    if tpe == 0:
        def getter(self, v):
            return getattr(self, "%s%d"%(core, v))
    elif tpe ==1 :
        def getter(self, v):
            return getattr(self, "%s_%s"%(core, v))        
    
    elif tpe ==2:
        def getter(self, v):
            return getattr(self, v) 
    return getter                 


def build_cl_getter(tpe,core,value):
    if tpe == 0:
        def getter(cl, v):
            return getattr(cl, "%s%d"%(core, v))
    elif tpe ==1 :
        def getter(cl, v):
            return getattr(cl, "%s_%s"%(core, v))        
    
    elif tpe ==2:
        def getter(cl, v):
            return getattr(cl, v)

    return classmethod(getter)


def build_iterator(name, values):
    def iterator(self, values=values):
        for v in values:
            yield getattr(self, name)(v)
    return iterator

def build_cl_iterator(name, values):
    def cl_iterator(cl, values=values):
        for v in values:
            yield getattr(cl, name)(v)
    return classmethod(cl_iterator)

def build_bridge_property(bridge_name, value):
    def bridge_property(self):
        return getattr(self, bridge_name)(value)        
    return property(bridge_property)


def build_bridge_func(path,last):
    spath = ".".join(p for p,_ in path)
    lp, lisfunc = last 
    if lisfunc:
        def bridge_func(self, value):
            for p,isfunc in path:
                if not isfunc:
                    self = getattr(self,p)
                    continue
                try:
                    v = self[p]
                except KeyError:
                    raise KeyError("Cannot jump to %r, missing %r default keyword is missing in parent"%(spath,p))  
                try:                
                    self = getattr(self,p)(v)
                except AttributeError:
                    raise KeyError("Cannot jump to %r, probably that %r default keyword value %r is wrong"%(spath,p,v))        
            return getattr(self,lp)(value)
    else:
        def bridge_func(self):
            for p,isfunc in path:
                if not isfunc:
                    self = getattr(self,p)
                    continue
                try:
                    v = self[p]
                except KeyError:
                    raise KeyError("Cannot jump to %r, missing %r default keyword is missing in parent"%(spath,p))  
                try:                
                    self = getattr(self,p)(v)
                except AttributeError:
                    raise KeyError("Cannot jump to %r, probably that %r default keyword is wrong"%(spath,p))        
            return getattr(self,lp)
    if lisfunc:                                
        return bridge_func
    else:
        return property(bridge_func)  

def build_path_func(path, fname):
    print (path, fname)
    def path_func(self, v):
        for p in path:
            self = getattr(self,p)
        return getattr(self, fname)(v)
    return path_func

def build_path_property(path, fname, value):
    print (path, fname, value)    
    def path_property(self):
        for p in path:
            self = getattr(self,p)
        return getattr(self, fname)(value)            
    return property(path_property)


def build_rec_class(CMname, path, FuncClass=None, **kwargs):

    definitions = []
    path = [(CMname, [])]+path

    rpath = path[::-1]
    subpath   = []
    subvalues = []
    lastCl = None
    clRecords = []

    for name, values in rpath:

        if name[:1].upper()!=name[:1]:
            raise ValueError("Class name must be capitalized got %r expecting %r"%(name, name.capitalize()))

        Cname = name.capitalize()
        kname = Cname[:1].lower()+Cname[1:]


        
        attrs = {}
        subcl = (RecObject,)
        if FuncClass:
            subcl = subcl+(FuncClass,)
        morecl = kwargs.get(Cname, None)
        if morecl:
            subcl = subcl+(morecl if isinstance(morecl, tuple) else (morecl,))

        tpe = -1

        if values:
            v = values[0]            
            if isinstance(v, basestring):
                if not len(v):
                    raise ValueError("'' invalid attr name for %r"%name)
                if v[:1]=="_":
                    tpe = 1 
                    childattrs = [kname+"_"+v for v in values]               
                else:
                    tpe = 2
                    childattrs = [v for v in values]         
            elif isinstance(v, int):
                tpe = 0
                childattrs = ["%s%s"%(kname,v) for v in values] 
            else:    
                raise ValueError("%r invalid attr name for %r"%(v,name))    
        else:
            childattrs = [kname]    
        subvalues.append((values, childattrs))
        subpath.append((kname,len(values)>0))

        #if len(subpath) > 1:
        #    for i in range(len(subpath)):
        #        sp = subpath[:i+1][::-1]
        #        attrs[""]    

        if lastCl:
            #attrs[lastCname] = lastCl
            attrs[lastCname] = lastCl
            if lastvalues:
                attrs[lastkname] = build_getter(lasttpe, lastkname, v)
                attrs["_"+lastkname] = build_cl_getter(lasttpe, lastkname, v)

                attrs["iter_%s"%lastkname]  = build_iterator(lastkname, lastvalues)
                attrs["_iter_%s"%lastkname] = build_cl_iterator("_"+lastkname, lastvalues)

                for v,attr in zip(lastvalues,lastchildattrs):
                    attrs[attr] = lastCl({lastkname:v})                    
            else:
                attrs[lastkname] = lastCl() 

            if len(subpath) > 2:
                rsubpath   = subpath[::-1]
                rsubvalues = subvalues[::-1]

                for i in range(2, len(rsubpath)):
                    sp = rsubpath[1:i] 
                    a  = rsubpath[i]
                    an,_ =a
                    attrs[an] = build_bridge_func(sp,a)
                    vls = rsubvalues[i]
                                        
                    if vls:
                        for v,at in zip(*vls):
                            attrs[at] = build_bridge_property(an,v)
            
            ## makes the class definition available for parents
            attrs.update(clRecords)            

        lastCl =  type(Cname, subcl, attrs)
        clRecords.append( (Cname, lastCl))
        lastCname = Cname
        lastkname = kname
        lastvalues = values
        lastchildattrs = childattrs
        lasttpe = tpe
        
    

    return lastCl  


def build_jump_func(path,fname):
    def jump_func(self, v):
        for p in path:
            self = getattr(self, p)
        return getattr(self,fname)(v)
    return jump_func  

def build_jump_property(path,fname, value):
    def jump_property(self):
        for p in path:
            self = getattr(self, p)
        return getattr(self,fname)(value)
    return property(jump_property)


def build_jumpers(cl, subs, path):
    for clName, fname, values, subsubs in subs:
        if len(values):
            if path:
                setattr(cl, fname, build_jump_func(path, fname))
                for attr,value in values:
                    setattr(cl, attr, build_jump_property(path,fname, value))
        else:
            build_jumpers(cl, subsubs, path+[fname])


def build_hierarchy(cl, **kwargs):
    records = []
    _build_hierarchy(cl, records, kwargs)
    build_jumpers(cl, records, [])       
    return records


def _build_hierarchy(cl, records, kwargs):    

    
    for name, obj in cl.__dict__.items():

        if isinstance(obj, type) and issubclass(obj, RecObject):
            record = add_instances(cl, name, obj, kwargs.get(name, []))            
            records.append(record)                                               
            _build_hierarchy(obj, record[3], kwargs)
    return records

def add_recclass(cl, name, Sub):
    if name[0].upper() != name[0]:
        raise ValueError("subclass of recobject must start with majuscule")
    if hasattr(cl, name):
        raise ValueError("subclass %r already exists"%name)    
    setattr(cl, name, Sub)
    

def add_instances(cl, name, Sub, values):
    if name[0].upper() != name[0]:
        raise ValueError("subclass of recobject must start with majuscule")
    corename = name[0].lower()+name[1:]

    if values:
        if hasattr(values,"keys"):
            idvalues = values.keys()
        else:
            idvalues = values
            values = {i:{} for i in idvalues}    

        first = idvalues[0]
        if isinstance(first,basestring):                        
            tpe = 1 if first[:1]=="_" else 2
        elif isinstance(first, int):
            tpe = 0
        else:
            raise ValueError("%r id values must be string or int"%name)

        if tpe==1:
            idvalues = [s.lstrip("_") for s in idvalues]    
            values   = {i:values.get(i, values.get(i, "_"+i)) for i in idvalues}

        setattr(cl, corename,  build_getter(tpe, corename, None))

        setattr(cl, "_"+corename,  build_cl_getter(tpe, corename, None))
        
        setattr(cl, "iter_"+corename,  build_iterator(corename, idvalues))
        
        setattr(cl, "_iter_"+corename,  build_cl_iterator(corename, idvalues))
        
        ###
        # build the subobjects                
        if tpe==0:
            attrs = ["%s%d"%(corename, v) for v in idvalues]
        elif tpe ==1 :
            attrs = ["%s_%s"%(corename, v) for v in idvalues]
        elif tpe ==2 :
            attrs = ["%s"%(v) for v in idvalues]
        
        
        for attr,v in zip(attrs, idvalues):
            o = Sub({corename:v}, **values[v])
            setattr(cl, attr, o)
        
        record = (name, corename, list(zip(attrs, idvalues)), [])
        
        
    else:
        setattr(cl, corename, Sub()) 
        record = (name, corename, [], [])
    return record    

     
