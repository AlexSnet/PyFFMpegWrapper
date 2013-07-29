#!/usr/bin/env python
# ~*~ coding: utf-8 ~*~
"""

"""
import re
import os
import sys
import time
import signal
import inspect
import StringIO
import threading
import subprocess
from weakref import WeakSet, WeakKeyDictionary


class Signal(object):
    def __init__(self):
        self._functions = WeakSet()
        self._methods = WeakKeyDictionary()

    def __call__(self, *args, **kargs):
        # Call handler functions
        for func in self._functions:
            func(*args, **kargs)

        # Call handler methods
        for obj, funcs in self._methods.items():
            for func in funcs:
                func(obj, *args, **kargs)

    def connect(self, slot):
        if inspect.ismethod(slot):
            if slot.__self__ not in self._methods:
                self._methods[slot.__self__] = set()

            self._methods[slot.__self__].add(slot.__func__)

        else:
            self._functions.add(slot)

    def disconnect(self, slot):
        if inspect.ismethod(slot):
            if slot.__self__ in self._methods:
                self._methods[slot.__self__].remove(slot.__func__)
        else:
            if slot in self._functions:
                self._functions.remove(slot)

    def clear(self):
        self._functions.clear()
        self._methods.clear()


class Stream(object):
    def __init__(self, source, executer, meta={}):
        self.__meta = dict()

        source_n= list()
        for c in [ [ c.strip() for c in  s.split(',') if c ] for s in source ]:
            source_n += c
        if '(default)' in source_n[-1]:
            source_n[-1] = source_n[-1][:-10]
            source_n.append('(default)')
        #source = source_n
        print source_n

        self.id = source_n[0]
        self.language = source_n[1][1:-1]
        self.default = '(default)' in source_n
        self.codec = executer.codecs[source_n[3]]

        self.__source_meta = meta

        if source[2] == 'Video':
            self.__type = 'video'
            video = {
                'codec' : source[3],
            }
            video['width'],video['height'] = map(int,str(re.findall(r", (\d+x\d+)", source[4])[0]).split('x'))
            fps = re.findall(r"(\d+\.\d+|\d+) (fps|tbr)", source[4])
            video['fps'] = float(fps[0][0]) if len(fps) else 'unknown'
            video['SAR'],video['DAR'] =  re.findall(r'SAR (\d+:\d+) DAR (\d+:\d+)', source[4])[0]
            self.__meta.update(video)

        elif source[2] == 'Audio':
            self.__type = 'audio'
            self.__meta['frequency'] = source_n[4].split(' ')[0]
            
        elif source[2] == 'Subtitle':
            self.__type = 'subtitle'
            
    def __repr__(self):
        return '<Stream %(id)s %(type)s %(codec)s %(language)s%(title)s%(additational_info)s>' % {
            'id' : self.id,
            'type' : self.type,
            'codec': self.codec.name,
            'language': self.language,
            'title' : ' (%s) '%self.title if self.title else '',
            'additational_info' : ''
        }

    @property
    def title(self):
        return self.__source_meta['title'] if 'title' in self.__source_meta.keys() else None

    @property
    def type(self):
        return self.__type

    @property
    def fps(self):
        if self.type != 'video':
            return None
        return self.__meta['fps']


class Codec_Dict(dict):

    @property
    def audio(self):
        return Codec_Dict([ c for c in self.items() if c[1].short_type == 'A' ])

    @property
    def video(self):
        return Codec_Dict([ c for c in self.items() if c[1].short_type == 'V' ])

    @property
    def subtitle(self):
        return Codec_Dict([ c for c in self.items() if c[1].short_type == 'S' ])

    @property
    def encoders(self):
        return Codec_Dict([ c for c in self.items() if c[1].meta['encoding']])

    @property
    def decoders(self):
        return Codec_Dict([ c for c in self.items() if c[1].meta['decoding']])

    @classmethod
    def _to_dict(cls, codec_list):
        return Codec_Dict([ (c.name,c) for c in codec_list])

class Codec(object):
    """
     D..... = Decoding supported
     .E.... = Encoding supported
     ..V... = Video codec
     ..A... = Audio codec
     ..S... = Subtitle codec
     ...I.. = Intra frame-only codec
     ....L. = Lossy compression
     .....S = Lossless compression
    """
    
    def __init__(self, rawstring):
        self.__meta = {
            'encoding'    : False,
            'decoding'    : False,
            'codec_type'  : None,
            'ifoc'        : None,
            'lossy'       : False,
            'lossless'    : False,

            'name'        : '',
            'desc'        : '',
        }
        rs = [ chunk.strip() for chunk in rawstring.strip().split(' ', 2)]

        self.__parse_opts(rs[0])
        self.__meta['name'] = rs[1]
        self.__meta['desc'] = rs[2] if len(rs)==3 else ''

    def __parse_opts(self, op):
        if 'D' in op:
            self.__meta['decoding'] = True
        if 'E' in op:
            self.__meta['encoding'] = True
        self.__meta['codec_type'] = op[2]
        if 'I' in op:
            self.__meta['ifoc'] = True
        if 'L' in op:
            self.__meta['lossy'] = True
        if 'S' in op:
            self.__meta['lossless'] = True

    @property
    def meta(self):
        return self.__meta

    @property
    def name(self):
        return self.__meta['name']

    @property
    def description(self):
        return self.__meta['description']

    @property
    def short_type(self):
        return self.__meta['codec_type']

    @property
    def prop(self):
        return '%s%s%s%s%s%s' % (
            'D' if self.__meta['decoding'] else '.',
            'E' if self.__meta['encoding'] else '.',
            self.short_type,
            'I' if self.__meta['ifoc'] else '.',
            'L' if self.__meta['lossy'] else '.',
            'S' if self.__meta['lossless'] else '.',
            )

    def __unicode__(self):
        return self.prop + ' %(name)s (%(desc)s)'%(self.__meta)

    def __repr__(self):
        return '<Codec: %s>'%self.__unicode__()

class FFMpeg(object):
    executable = None

    def __init__(self, executable=None):
        self.executable = executable or self.__find_executable()
        self.stdout = StringIO.StringIO()
        self.stderr = StringIO.StringIO()

    def __find_executable(self):
        pgm = 'ffmpeg'
        if os.sys.platform in ('win32','cygwin','win64'):
            pgm='ffmpeg.exe'
        path=os.getenv('PATH')
        for p in path.split(os.path.pathsep):
            p=os.path.join(p,pgm)
            if os.path.exists(p) and os.access(p,os.X_OK):
                return p
        raise Exception('FFMpeg executable can not be found. Please setup it manualy.')

    @property
    def version(self):
        if not hasattr(self, '__version'):
            out = subprocess.Popen([self.executable, "-version"], stderr=subprocess.PIPE, stdout=subprocess.PIPE).communicate()[0]
            self.__version = re.findall(r'ffmpeg version (\d+.\d+.\d+)',out)[0]
        return self.__version

    def execute(self, source, *arguments, **kwargs):
        def parse_kwargs(kwargs):
            args=list()
            for k,v in kwargs.items():
                args.append('-%s'%k)
                args.append(v)
            return args
        return subprocess.Popen([self.executable, "-i", source]+list(arguments)+parse_kwargs(kwargs), stderr=subprocess.PIPE, stdout=subprocess.PIPE)       

    @property
    def codecs(self):
        if not hasattr(self, '__codecs'):
            out = subprocess.Popen([self.executable, "-codecs"], stderr=subprocess.PIPE, stdout=subprocess.PIPE).communicate()[0]
            out = [ chunk.strip() for chunk in out.split('\n')]
            out = out[out.index('-------'):]
            self.__codecs =  Codec_Dict._to_dict([ Codec(rs) for rs in out if len(rs)>7 ])
        return self.__codecs

    def __repr__(self):
        return '<FFMpeg at %s version %s>'%(self.executable, self.version)

class Encoder(threading.Thread):
    def __init__(self):
        super(Encoder, self).__init__()
        self.progress = Signal()
        self.finished = Signal()

        self.ffmpeg_output = Signal()
        
        self.__state = -1

    def _set_executable(self, executable):
        self.__executable = executable

    def _set_source(self, source):
        self.__source = source

    def _set_dest(self, dest):
        self.__dest = dest
    
    def run(self):
        cmd = (
            self.__executable,
            '-i',
            self.__source.source,
            '-y',
            '-stats',
            self.__dest
            )
        self.__state = 0
        start_time = time.time()
        self.process = subprocess.Popen(cmd, bufsize=10, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        totalframes = self.__source.frames
        self.last_frame = 0
        encoding_started = False
        regexp = re.compile(r"frame=([ \t]?|\s+)(?P<frame>\d+)\s+")
        line = ''
        while not self.process.poll():
            line += self.process.stdout.read(100)
            self.ffmpeg_output(line=line)

            if not encoding_started:
                if 'frame=' in line:
                    line = ''
                    encoding_started=True
                    self.__state = 10
                continue

            if 'frame=' in line:
                finded = regexp.findall(line)
                if not finded:
                    continue
                else:
                    self.last_frame = int(finded[-1][1]) if int(finded[-1][1])>self.last_frame else self.last_frame
                    self.encoding_progress = float( (float(self.last_frame)/float(totalframes))*100)
                    self.progress(progress=self.encoding_progress, frames=self.last_frame)
            else:
                continue

            line = ''
        
        exit_status = self.process.wait()
        end_time = time.time()

        if exit_status == 0:
            self.last_frame = totalframes
            self.finished()
        else:
            raise Exception('Process abnormally ended with status code %i'%exit_status)

    def pause(self):
        if self.__paused:
            self.unpause()
            self.__paused = False
        else:
            os.kill(self.process.pid,signal.SIGSTOP)
            self.__state = 1
            self.__paused = True

    def unpause(self):
        os.kill(self.process.pid,signal.SIGCONT)
        self.__state = 10

class Movie(object):
    def __init__(self, src='', executer=None):
        if not os.path.exists(src):
            raise Exception('Can not find file "%s". Check file path.'%src)
        self.source = os.path.realpath(src)

        # Step 1: trying to find already existen executer
        if not executer:
            for i in globals():
                if isinstance(i, FFMpeg):
                    executer = i
                    break
        # Step 2: creating instance of ffmpeg
        if not executer:
            executer = FFMpeg()
        self.executer = executer

        self.__meta = {
            'duration'  : {
                'seconds' : 0,
                'time'    : ''
            },
            'title'     : '',
            'bitrate'   : 0,
            'streams'   : []
        }
        self.__gather_info()

    def __gather_info(self):
        ffmpeg = self.executer.execute(self.source)
        self.__info_output = ffmpeg.communicate()[1]

        self.__get_duration()
        self.__get_title()
        self.__get_sources()

    def __secs(self, h, m, s):
        return (((h*60)+m)*60)+s

    def __get_duration(self):
        match = re.search("(\\d+):(\\d+):(\\d+)\\.\\d+", self.__info_output)
        if match == None: return 0
        dur = match.groups()
        self.__meta['duration']['seconds'] = self.__secs(int(dur[0]), int(dur[1]), int(dur[2]))
        self.__meta['duration']['time'] = '%i:%i:%i' % (int(dur[0]), int(dur[1]), int(dur[2]))

    def __get_title(self):
        regex = re.compile("title.+: (.*)$",re.MULTILINE)
        titles = regex.findall(self.__info_output)
        if len(titles):
            self.__meta['title'] = titles[0]

    def __get_sources(self):
        regex = re.compile("Stream #(\d+:\d+)(\(\w+\))?: (\w+): (\w+)(.*)")
        info_text = self.__info_output.replace('\\n', '\n')
        # sources = regex.findall(info_text)
        
        info_text = info_text.split('\n')
        for line_no in range(0,len(info_text)):
            line = info_text[line_no].strip()
            if 'Stream #' in line:
                try:
                    source = regex.findall(line)[0]
                    meta = {}
                    print source
                    if line_no+1 < len(info_text) and 'Metadata' in info_text[line_no+1]:
                        i = 2
                        
                        while line_no+i < len(info_text):
                            ln = info_text[line_no+i].strip()
                            i+=1
                            if 'Stream' in ln or ln == 'At least one output file must be specified':
                                break
                            meta_temp = [a.strip() for a in ln.split(':',1)]
                            meta.update({meta_temp[0]:meta_temp[1]})
                    print meta
                    self.__meta['streams'].append(Stream(source, self.executer, meta=meta)) 
                except:
                    pass

    def printMeta(self):
        print "File\t: %s" % os.path.basename(self.source)
        print "Title\t: %s" % self.__meta['title'] or 'unknown'
        
        if self.__meta['duration']['seconds']:
            print "Duration: %s (%is)" % (self.__meta['duration']['time'], self.__meta['duration']['seconds'])
        else:
            print "Duration: unknown"

        
        if self.__meta['streams']:
            print 'Streams:'
            for source in self.__meta['streams']:
                print '\t', source
    
    def get_video_stream(self):
        for stream in self.__meta['streams']:
            if stream.type == 'video':
                return stream

    @property
    def frames(self):
        vstream = self.get_video_stream()
        return int(self.__meta['duration']['seconds'] * vstream.fps)

    def encode(self, dest):
        encoder =  Encoder()
        encoder._set_source(self)
        encoder._set_executable(self.executer.executable)
        encoder._set_dest(dest)
        return encoder


if __name__ == '__main__':
    executer = FFMpeg()
    
    print 'FFMPeg Version:', executer.version
    print 'Bin:', executer.executable
    print '\n\n'

    print 'Codecs'
    nlen = max(map(len,executer.codecs.keys()))
    for t in ('video', 'audio', 'subtitle'):
        print '\t%s:' % t.capitalize()
        for codec in getattr(executer.codecs,t).items():
            print str("\t\t{:<"+str(nlen)+"} : {}").format(codec[0], codec[1].__unicode__())
    

    print
    print (' '*10+'-'*10)*5
    print

    movie_dir = os.path.expanduser('~/Movies/')
    movies = [ os.path.join(movie_dir,f) for f in os.listdir(movie_dir) if os.path.isfile(os.path.join(movie_dir,f)) and str(f.split('.')[-1]).lower() in ('mkv','avi','flv','mp4') ]
    for movie in movies:    
        m = Movie(movie, executer)
        m.printMeta()
    

    # def handle_progress(progress, frames):
    #     print '%0.2f%%'%progress
        
    # def ffmpeg_output(line):
    #     # print 'FFO: %s' % line
    #     pass


    # encoder = movie.encode('/Users/alex/Movies/ironsky.mp4')
    # encoder.ffmpeg_output.connect(ffmpeg_output)
    # encoder.progress.connect(handle_progress)
    # encoder.start()
    

