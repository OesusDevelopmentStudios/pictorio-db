build:
	cmake -B build -S .
	$(MAKE) -C build
	rm -f pictorio-db
	mv ./build/src/pictorio-db .

clean:
	rm -f pictorio-db
	rm -rf build
