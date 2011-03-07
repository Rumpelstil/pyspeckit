import gaussfitter
import matplotlib
import matplotlib.cbook as mpcb
import matplotlib.pyplot as pyplot
import numpy as np

interactive_help_message = """
Left-click or hit 'p' twice to select a fitting range, then middle-click or hit
'm' twice to select a peak and width.  When you're done, right-click or hit 'd'
to perform the fit and disconnect the mouse and keyboard.  '?' will print this
help message again.
"""


class Specfit(object):

    def __init__(self,Spectrum):
        self.model = None
        self.modelpars = None
        self.modelerrs = None
        self.modelplot = None
        self.guessplot = []
        self.fitregion = []
        self.ngauss = 0
        self.nclicks_b1 = 0
        self.nclicks_b2 = 0
        self.gx1 = 0
        self.gx2 = Spectrum.data.shape[0]
        self.guesses = []
        self.click = 0
        self.fitkwargs = {}
        self.auto = False
        self.autoannotate = True
        self.Spectrum = Spectrum
        self.specplotter = self.Spectrum.plotter
        self.gaussleg=None
        self.residuals=None
        self.setfitspec()
        #self.seterrspec()

    def __call__(self, interactive=False, usemoments=True, fitcolor='r',
            multifit=False, guesses=None, annotate=True, save=True,
            **kwargs):
        """
        Fit gaussians to a spectrum

        guesses = [height,amplitude,center,width]


        If you pass interactive=True, you can fit n gaussians using the mouse
        and/or keyboard:
            Left click or 'p': Set fitting region.  Two clicks sets the region,
                which will be highlighted.
            Middle click or 'm': Select peaks and peak widths.  The first click
                will mark a peak X-location and height with an X, the second
                click will mark the half-width-half-max location with a red
                line that represents the full-width-half-max
            Right click or 'd': Disconnect the plot and perform the fit.
        """
  
        self.fitcolor = fitcolor
        self.clear()

        self.ngauss = 0
        self.fitkwargs = kwargs
        if interactive:
            if self.specplotter.axis is None:
                raise Exception("Interactive fitting requires a plotter.")
            print interactive_help_message
            self.nclicks_b1 = 0
            self.nclicks_b2 = 0
            self.guesses = []
            self.click = self.specplotter.axis.figure.canvas.mpl_connect('button_press_event',self.makeguess)
            self.keyclick = self.specplotter.axis.figure.canvas.mpl_connect('key_press_event',self.makeguess)
            self.autoannotate = annotate
        elif multifit:
            if guesses is None:
                print "You must input guesses when using multifit.  Also, baseline (continuum fit) first!"
            else:
                self.guesses = guesses
                self.multifit()
                self.autoannotate = annotate
        else:
            #print "Non-interactive, 1D fit with automatic guessing"
            if self.Spectrum.baseline.order is None:
                self.Spectrum.baseline.order=0
                self.onedfit(usemoments=usemoments,annotate=annotate,**kwargs)
            else:
                self.onedfit(usemoments=usemoments,annotate=annotate,
                        vheight=False,height=0.0,**kwargs)
            if self.specplotter.autorefresh: self.specplotter.refresh()
        if save: self.savefit()

    def EQW(self, plot=False, plotcolor='g', annotate=False, alpha=0.5, loc='lower left'):
        """
        Returns the equivalent width (integral of "baseline" or "continuum"
        minus the spectrum) over the selected range
        """
        if np.median(self.Spectrum.baseline.basespec) == 0:
            raise ValueError("Baseline / continuum is zero: equivalent width is undefined.")
        elif np.median(self.Spectrum.baseline.basespec) < 0:
            print "WARNING: Baseline / continuum is negative: equivalent width is poorly defined."
        diffspec = (self.Spectrum.baseline.basespec - self.Spectrum.data)
        dx = np.abs((self.Spectrum.xarr[self.gx2-1]-self.Spectrum.xarr[self.gx1]) / (self.gx2-self.gx1))
        sumofspec = diffspec[self.gx1:self.gx2].sum() * dx
        eqw = sumofspec / np.median(self.Spectrum.baseline.basespec)
        if plot:
            midpt_pixel = np.round((self.gx1+self.gx2)/2.0)
            midpt       = self.Spectrum.xarr[midpt_pixel]
            midpt_level = self.Spectrum.baseline.basespec[midpt_pixel]
            print "EQW plotting: ",midpt,midpt_pixel,midpt_level,eqw
            self.specplotter.axis.fill_between(
                    [midpt-eqw/2.0,midpt+eqw/2.0],
                    [0,0],
                    [midpt_level,midpt_level],
                    color=plotcolor,
                    alpha=alpha,
                    label='EQW: %0.3g' % eqw)
            if annotate:
                self.specplotter.axis.legend(
                        [(matplotlib.collections.CircleCollection([0],facecolors=[plotcolor],edgecolors=[plotcolor]))],
                        [('EQW: %0.3g' % eqw)], 
                        markerscale=0.01, borderpad=0.1, handlelength=0.1,
                        handletextpad=0.1, loc=loc)
            if self.specplotter.autorefresh:
                self.specplotter.refresh()
        return eqw

    
    def seterrspec(self,usestd=None,useresiduals=True):
        """
        Simple wrapper function to set the error spectrum; will either use the
        input spectrum or determine the error using the RMS of the residuals,
        depending on whether the residuals exist.
        """
        if self.Spectrum.error is not None and not usestd:
            self.errspec = self.Spectrum.error
        elif self.residuals is not None and useresiduals: 
            self.errspec = np.ones(self.spectofit.shape[0]) * self.residuals.std()
        else: self.errspec = np.ones(self.spectofit.shape[0]) * self.spectofit.std()

    def setfitspec(self):
        """
        Set the spectrum that will be fit.  This is primarily to remove NANs
        from consideration: if you simply remove the data from both the X-axis
        and the Y-axis, it will not be considered for the fit, and a linear
        X-axis is not needed for fitting.

        However, it may be possible to do this using masked arrays instead of
        setting errors to be 1e10....
        """
        self.spectofit = np.copy(self.Spectrum.data)
        if hasattr(self.Spectrum,'baseline'):
            if self.Spectrum.baseline.subtracted is False and self.Spectrum.baseline.basespec is not None:
                self.spectofit -= self.Spectrum.baseline.basespec
        OKmask = (self.spectofit==self.spectofit)
        self.spectofit[(True-OKmask)] = 0
        self.seterrspec()
        self.errspec[(True-OKmask)] = 1e10

    def multifit(self):
        self.ngauss = len(self.guesses)/3
        self.setfitspec()
        if self.fitkwargs.has_key('negamp'): self.fitkwargs.pop('negamp')
        mpp,model,mpperr,chi2 = gaussfitter.multigaussfit(
                self.Spectrum.xarr[self.gx1:self.gx2], 
                self.spectofit[self.gx1:self.gx2], 
                err=self.errspec[self.gx1:self.gx2],
                ngauss=self.ngauss,
                params=self.guesses,
                **self.fitkwargs)
        self.chi2 = chi2
        self.dof  = self.gx2-self.gx1-self.ngauss*3
        self.model = model
        self.modelpars = mpp.tolist()
        self.modelerrs = mpperr.tolist()
        if self.specplotter.axis is not None:
            self.plot_fit()
        self.residuals = self.spectofit[self.gx1:self.gx2] - self.model
        if self.autoannotate:
            self.annotate()
    
    def onedfit(self, usemoments=True, annotate=True, vheight=True, height=0, negamp=None, **kwargs):
        self.ngauss = 1
        self.auto = True
        self.setfitspec()
        if usemoments: # this can be done within gaussfit but I want to save them
            self.guesses = gaussfitter.onedmoments(
                    self.Spectrum.xarr[self.gx1:self.gx2],
                    self.spectofit[self.gx1:self.gx2],
                    vheight=vheight,negamp=negamp,**kwargs)
            if vheight is False: self.guesses = [height]+self.guesses
        else:
            if negamp: self.guesses = [height,-1,0,1]
            else:  self.guesses = [height,1,0,1]
        mpp,model,mpperr,chi2 = gaussfitter.onedgaussfit(
                self.Spectrum.xarr[self.gx1:self.gx2],
                self.spectofit[self.gx1:self.gx2],
                err=self.errspec[self.gx1:self.gx2],
                vheight=vheight,
                params=self.guesses,
                **self.fitkwargs)
        self.chi2 = chi2
        self.dof  = self.gx2-self.gx1-self.ngauss*3-vheight
        if vheight: 
            self.Spectrum.baseline.baselinepars = mpp[:1] # first item in list form
            self.model = model - mpp[0]
        else: self.model = model
        self.residuals = self.spectofit[self.gx1:self.gx2] - self.model
        self.modelpars = mpp[1:].tolist()
        self.modelerrs = mpperr[1:].tolist()
        if self.specplotter.axis is not None:
            self.plot_fit()
        if annotate:
            self.annotate()
            if vheight: self.Spectrum.baseline.annotate()

    def plot_fit(self):
        if self.Spectrum.baseline.subtracted is False and self.Spectrum.baseline.basespec is not None:
            plotmodel = self.model+self.specplotter.offset+self.Spectrum.baseline.basespec
        else:
            plotmodel = self.model+self.specplotter.offset
        self.modelplot = self.specplotter.axis.plot(
                self.Spectrum.xarr[self.gx1:self.gx2],
                plotmodel,
                color=self.fitcolor, linewidth=0.5)

    def fullsizemodel(self):
        """
        If the gaussian was fit to a sub-region of the spectrum,
        expand it (with zeros) to fill the spectrum.  You can 
        always recover the original by:
        origmodel = model[gx1:gx2]
        """

        if self.model.shape != self.Spectrum.data.shape:
            temp = np.zeros(self.Spectrum.data.shape)
            temp[self.gx1:self.gx2] = self.model
            self.model = temp
            self.residuals = self.spectofit - self.model

    def plotresiduals(self,fig=None,axis=None,clear=True,**kwargs):
        """
        Plot residuals of the fit.  Specify a figure or
        axis; defaults to figure(2).

        kwargs are passed to matplotlib plot
        """
        if axis is None:
            fig=figure(2)
            self.residualaxis = gca()
            if clear: self.residualaxis.clear()
        else:
            self.residualaxis = axis
            if clear: self.residualaxis.clear()
        self.residualplot = self.residualaxis.plot(self.Spectrum.xarr[self.gx1:self.gx2],
                self.residuals,drawstyle='steps-mid',
                linewidth=0.5, color='k', **kwargs)
        if self.specplotter.vmin is not None and self.specplotter.vmax is not None:
            self.residualaxis.set_xlim(self.specplotter.vmin,self.specplotter.vmax)
        self.residualaxis.figure.canvas.draw()

    def annotate(self,loc='upper right'):
        #text(xloc,yloc     ,"c=%g" % self.modelpars[1],transform = self.specplotter.axis.transAxes)
        #text(xloc,yloc-0.05,"w=%g" % self.modelpars[2],transform = self.specplotter.axis.transAxes)
        #text(xloc,yloc-0.10,"a=%g" % self.modelpars[0],transform = self.specplotter.axis.transAxes)
        self.clearlegend()
        pl = matplotlib.collections.CircleCollection([0],edgecolors=['k'])
        self.gaussleg = self.specplotter.axis.legend(
                tuple([pl]*3*self.ngauss),
                tuple(mpcb.flatten(
                    [("c%i=%6.4g $\\pm$ %6.4g" % (jj,self.modelpars[1+jj*3],self.modelerrs[1+jj*3]),
                      "w%i=%6.4g $\\pm$ %6.4g" % (jj,self.modelpars[2+jj*3],self.modelerrs[2+jj*3]),
                      "a%i=%6.4g $\\pm$ %6.4g" % (jj,self.modelpars[0+jj*3],self.modelerrs[0+jj*3]))
                      for jj in range(self.ngauss)])),
                loc=loc,markerscale=0.01,
                borderpad=0.1, handlelength=0.1, handletextpad=0.1
                )
        self.gaussleg.draggable(True)
        self.specplotter.axis.add_artist(self.gaussleg)
        if self.specplotter.autorefresh: self.specplotter.refresh()

    def selectregion(self,event):
        if self.nclicks_b1 == 0:
            self.gx1 = np.argmin(abs(event.xdata-self.Spectrum.xarr))
            self.nclicks_b1 += 1
        elif self.nclicks_b1 == 1:
            self.gx2 = np.argmin(abs(event.xdata-self.Spectrum.xarr))
            self.nclicks_b1 -= 1
            if self.gx1 > self.gx2: self.gx1,self.gx2 = self.gx2,self.gx1
            if abs(self.gx1-self.gx2) > 3: # can't fit w/ fewer data than pars
                self.fitregion = self.specplotter.axis.plot(
                        self.Spectrum.xarr[self.gx1:self.gx2],
                        self.Spectrum.data[self.gx1:self.gx2]+self.specplotter.offset,
                        drawstyle='steps-mid',
                        color='c')
                if self.guesses == []:
                    self.guesses = gaussfitter.onedmoments(
                            self.Spectrum.xarr[self.gx1:self.gx2],
                            self.spectofit[self.gx1:self.gx2],
                            vheight=0)
                    self.ngauss = 1
                    self.auto = True
            else:
                print "Fitting region is too small (channels %i:%i).  Try again." % (self.gx1,self.gx2)

    def guesspeakwidth(self,event):
        """
        Interactively guess the peak height and width from user input

        Width is assumed to be half-width-half-max
        """
        if self.nclicks_b2 % 2 == 0:
            if self.auto:
                self.guesses[:2] = [event.ydata,event.xdata]
            else:
                self.guesses += [event.ydata,event.xdata,1]
                self.ngauss += 1
            self.nclicks_b2 += 1
            self.guessplot += [self.specplotter.axis.scatter(event.xdata,event.ydata,marker='x',c='r')]
        elif self.nclicks_b2 % 2 == 1:
            self.guesses[-1] = abs(event.xdata-self.guesses[-2]) / np.sqrt(2*np.log(2))
            self.nclicks_b2 += 1
            self.guessplot += self.specplotter.axis.plot([event.xdata,
                2*self.guesses[-2]-event.xdata],[event.ydata]*2,
                color='r')
            if self.auto:
                self.auto = False
            if self.nclicks_b2 / 2 > self.ngauss:
                print "There have been %i middle-clicks but there are only %i gaussians" % (self.nclicks_b2,self.ngauss)
                self.ngauss += 1

    def clear(self,legend=True):
        if self.modelplot is not None:
            for p in self.modelplot:
                p.set_visible(False)
        if legend: self.clearlegend()

    def makeguess(self,event):
        if hasattr(event,'button'):
            button = event.button
        elif hasattr(event,'key'):
            button = event.key

        if button in ('p','P','1',1):
            self.selectregion(event)
        elif button in ('m','M','2',2):
            self.guesspeakwidth(event)
        elif button in ('d','D','3',3):
            self.specplotter.figure.canvas.mpl_disconnect(self.click)
            self.specplotter.figure.canvas.mpl_disconnect(self.keyclick)
            if self.ngauss > 0:
                print len(self.guesses)/3," Guesses: ",self.guesses," X channel range: ",self.gx1,self.gx2
                if len(self.guesses) % 3 == 0:
                    self.multifit()
                    for p in self.guessplot + self.fitregion:
                        p.set_visible(False)
                else: 
                    print "error, wrong # of pars"
        elif button in ('?'):
            print interactive_help_message
        if self.specplotter.autorefresh: self.specplotter.refresh()

    def clearlegend(self):
        if self.gaussleg is not None: 
            self.gaussleg.set_visible(False)
            if self.gaussleg in self.specplotter.axis.artists:
                self.specplotter.axis.artists.remove(self.gaussleg)
        if self.specplotter.autorefresh: self.specplotter.refresh()
    
    def savefit(self):
        if self.modelpars is not None and hasattr(self.Spectrum,'header'):
            for ii,p in enumerate(self.modelpars):
                if ii % 3 == 0: self.Spectrum.header.update('AMP%1i' % (ii/3),p,comment="Gaussian best fit amplitude #%i" % (ii/3))
                if ii % 3 == 1: self.Spectrum.header.update('CEN%1i' % (ii/3),p,comment="Gaussian best fit center #%i" % (ii/3))
                if ii % 3 == 2: self.Spectrum.header.update('WID%1i' % (ii/3),p,comment="Gaussian best fit width #%i" % (ii/3))
